"""Compare quota limiting's decisions with billing's limiting spine.

The spine is the billing service's own record of each customer's limits and of whether it enforces them.
Reports only: nothing here changes what gets limited. Each side is reduced to a level per
organization and resource, and a pair of levels that disagree gets a label that says why.
A mismatch is reported once, when a usage report that started after it was first seen has
had a full quota run to reach billing's limiting. Until then it may only be a matter of timing.
"""

import json
from collections import Counter
from collections.abc import Mapping, Set
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, TypedDict

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.cloud_utils import get_cached_instance_license, is_cloud
from posthog.ph_client import feature_enabled_or_false, ph_scoped_capture
from posthog.redis import get_client
from posthog.utils import get_instance_region

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import BillingLimit, BillingLimits
from ee.billing.quota_limiting import GRACE_PERIOD_EXEMPT_RESOURCES, QuotaLimitingRunResult, QuotaResource

logger = structlog.get_logger(__name__)

Key = tuple[str, str]  # organization id, resource
QuotaLevel = Literal["none", "limited", "suspended"]
SpineLevel = Literal["absent", "exempt", "enforced", "over", "under"]
Label = Literal["no_spine_limit", "exempt", "grace", "near_limit", "unexplained"]


class Sighting(TypedDict):
    since: str
    confirmed: bool


class State(TypedDict):
    usage_through: str | None  # what billing answered on the previous run
    mismatches: dict[str, Sighting]  # by "organization:resource:quota level:spine level:label"


class Mismatch(TypedDict):
    organization_id: str
    resource: str
    label: Label
    quota_level: QuotaLevel
    spine_level: SpineLevel
    usage: str | None
    limit: str | None
    grace_expiry: str | None
    since: str


EMPTY: State = {"usage_through": None, "mismatches": {}}
STATE_KEY = "@posthog/quota-limiting/spine-comparison"
STATE_TTL = timedelta(days=7)
MISMATCH_EVENT = "quota limiting spine mismatch"
COMPARISON_FLAG = "quota-limiting-spine-comparison"
NEAR_LIMIT = Decimal("0.01")
# One analytics batch: a hanging capture endpoint holds the run for its retries only. A backlog takes several runs.
CONFIRMED_PER_RUN = 100
# Billing also holds limits on products that quota limiting has no quota for.
RESOURCES = frozenset(resource.value for resource in QuotaResource)
CREDIT_RESOURCES = frozenset(resource.value for resource in GRACE_PERIOD_EXEMPT_RESOURCES)

# The label for each pair of levels, quota limiting's first. None means they agree.
LABELS: dict[tuple[QuotaLevel, SpineLevel], Label | None] = {
    ("none", "absent"): None,
    ("none", "exempt"): None,
    ("none", "under"): None,
    ("suspended", "over"): None,
    ("limited", "enforced"): None,
    # The spine holds dollar limits only, so a free allocation has no row there.
    ("limited", "absent"): "no_spine_limit",
    ("suspended", "absent"): "no_spine_limit",
    # Quota limiting ignores never_drop_data on credit products. Anywhere else this pair is unexplained.
    ("limited", "exempt"): "exempt",
    ("suspended", "exempt"): "exempt",
    # Both say over the limit, and only one is enforcing: trust-score grace against the spine's flat grace.
    ("limited", "over"): "grace",
    ("suspended", "enforced"): "grace",
    ("none", "enforced"): "unexplained",
    ("none", "over"): "unexplained",
    ("limited", "under"): "unexplained",
    ("suspended", "under"): "unexplained",
}


def quota_levels(run: QuotaLimitingRunResult) -> dict[Key, QuotaLevel]:
    """Quota limiting's level for each organization and resource it limits or suspends.

    An organization limited on a resource it has not used is left out. Quota limiting counts
    zero usage against a zero allowance as limited, and that is not a limit the spine could hold.
    """
    decisions: dict[QuotaLevel, dict[str, dict[str, int]]] = {
        "limited": run.quota_limited_orgs,
        "suspended": run.quota_limiting_suspended_orgs,
    }
    return {
        (organization_id, resource): level
        for level, by_resource in decisions.items()
        for resource, organizations in by_resource.items()
        for organization_id in run.orgs_with_usage.get(resource, ())
        if organization_id in organizations
    }


def _spine_level(row: BillingLimit | None) -> SpineLevel:
    if row is None:
        return "absent"
    if row["never_drop_data"]:
        return "exempt"
    if row["enforced"]:
        return "enforced"
    return "over" if row["over_limit"] else "under"


def _near_limit(row: BillingLimit) -> bool:
    """Quota limiting stops ingestion at the limit, so the usage billing sees stalls around it."""
    usage, limit = Decimal(row["usage"]), Decimal(row["limit"])
    return abs(usage - limit) <= NEAR_LIMIT * limit


def compare(
    quota: Mapping[Key, QuotaLevel],
    spine: BillingLimits,
    previous: State,
    now: datetime,
    discarded: Set[str] = frozenset(),
) -> tuple[State, list[Mismatch]]:
    """The next state, and the mismatches this run confirmed.

    `quota` is from `quota_levels`, `spine` is billing's answer, `previous` is the state this
    returned on the run before. A mismatch that goes away is forgotten, so it starts over if it
    returns, and so does one whose levels or label change. The organizations in `discarded` kept
    their earlier limits when the run threw their decisions away, so they are not compared and
    what was seen of them stands. A run confirms `CONFIRMED_PER_RUN` at most, and the rest wait
    for the next.
    """
    reported = spine["usage_through"]
    if reported is None:
        # Billing has nothing to compare, and while its limiting is off it folds no usage either.
        # So what was not confirmed starts over: a report from this time would confirm it unfolded.
        kept = {name: seen for name, seen in previous["mismatches"].items() if seen["confirmed"]}
        return State(usage_through=previous["usage_through"], mismatches=kept), []
    rows = {(row["organization_id"], row["resource"]): row for row in spine["limits"] if row["resource"] in RESOURCES}
    # Billing marks a report processed before limiting has folded it, so trust the one from a run ago.
    folded = datetime.fromisoformat(previous["usage_through"]) if previous["usage_through"] else None
    mismatches = {name: seen for name, seen in previous["mismatches"].items() if name.split(":")[0] in discarded}
    confirmed: list[Mismatch] = []
    for key in sorted(key for key in quota.keys() | rows.keys() if key[0] not in discarded):
        organization_id, resource = key
        row = rows.get(key)
        quota_level: QuotaLevel = quota.get(key, "none")
        spine_level = _spine_level(row)
        label = LABELS[quota_level, spine_level]
        if label is None:
            continue
        if label == "unexplained" and row is not None and _near_limit(row):
            label = "near_limit"
        if label == "exempt" and resource not in CREDIT_RESOURCES:
            label = "unexplained"
        name = ":".join((organization_id, resource, quota_level, spine_level, label))
        seen = previous["mismatches"].get(name) or Sighting(since=now.isoformat(), confirmed=False)
        due = (
            not seen["confirmed"]
            and folded is not None
            and datetime.fromisoformat(seen["since"]) < folded
            and len(confirmed) < CONFIRMED_PER_RUN
        )
        mismatches[name] = Sighting(since=seen["since"], confirmed=seen["confirmed"] or due)
        if due:
            confirmed.append(
                Mismatch(
                    organization_id=organization_id,
                    resource=resource,
                    label=label,
                    quota_level=quota_level,
                    spine_level=spine_level,
                    usage=row["usage"] if row else None,
                    limit=row["limit"] if row else None,
                    grace_expiry=row["grace_expiry"] if row else None,
                    since=seen["since"],
                )
            )
    return State(usage_through=reported, mismatches=mismatches), confirmed


def labels(state: State) -> Counter[str]:
    """How many mismatches the state holds under each label."""
    return Counter(name.rsplit(":", 1)[-1] for name in state["mismatches"])


def _enabled() -> bool:
    """Whether the flag is on for this region. Read from the flags the worker holds, so no run waits on a request."""
    return feature_enabled_or_false(
        COMPARISON_FLAG,
        "internal_billing_events",
        person_properties={"region": get_instance_region()},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def compare_with_spine(run: QuotaLimitingRunResult) -> None:
    """Report where billing's limiting disagrees with this quota run. Off unless its flag is on."""
    license = get_cached_instance_license()
    if not is_cloud() or license is None or not _enabled():
        return
    quota = quota_levels(run)
    spine = BillingManager(license).get_limiting(sorted({organization_id for organization_id, _ in quota}))
    redis = get_client()
    previous: State = json.loads(redis.get(STATE_KEY) or "null") or EMPTY
    state, confirmed = compare(quota, spine, previous, timezone.now(), run.discarded_orgs)
    # The events are delivered before the state says so. A delivery that fails raises, and the next run repeats it.
    with ph_scoped_capture(event_region=get_instance_region(), raise_on_error=True) as capture:
        for mismatch in confirmed:
            capture(
                distinct_id=mismatch["organization_id"],
                event=MISMATCH_EVENT,
                properties=dict(mismatch),
                groups={"instance": settings.SITE_URL, "organization": mismatch["organization_id"]},
            )
    redis.set(STATE_KEY, json.dumps(state), ex=STATE_TTL)
    decided = sum(map(len, (*run.quota_limited_orgs.values(), *run.quota_limiting_suspended_orgs.values())))
    logger.info(
        "quota_limiting_spine_comparison",
        usage_through=spine["usage_through"],
        compared=len(quota),
        left_out=decided - len(quota),
        confirmed=dict(Counter(mismatch["label"] for mismatch in confirmed)),
        mismatches=dict(labels(state)),
    )
