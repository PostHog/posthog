"""The case file a frontier model reviews for a severe save: the function, its edit and test history, the account,
and every other function in the organization.

Built from Postgres only, bounded in size, and without secret input values.
"""

import json
from dataclasses import asdict, replace
from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.cdp.backend.abuse import rules
from products.cdp.backend.abuse.classifier import build_state
from products.cdp.backend.abuse.shadow import ScoredHogFunction, content_of
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.ml_inference.backend.facade.contracts import JsonValue

MAX_HISTORY_ENTRIES = 30
MAX_ORG_FUNCTIONS = 50
MAX_HOSTS_PER_FUNCTION = 20
MAX_HISTORY_CODE_CHARS = 4_000
MAX_CASE_FILE_CHARS = 200_000
_TRUNCATED_MARKER = " [truncated]"
# Only these fields of an update show their new value. The activity log masks the inputs, but not every field that
# can hold a secret: the default of a secret input sits unmasked in the inputs schema.
_HISTORY_VALUE_FIELDS = frozenset({"hog", "enabled"})


@frozen
class Classification:
    rule_hits: tuple[str, ...]
    scores: dict[str, float] | None
    risk_score: float | None
    would_alert: bool
    would_block: bool
    set_aside_scores: dict[str, str]
    model_alert_gates: tuple[str, ...]
    outbound_call: bool
    failure: str | None


@frozen
class FunctionUnderReview:
    name: str | None
    type: str | None
    template_id: str | None
    code_modified_from_template: bool | None
    enabled: bool
    created_at: datetime
    saved_at: datetime
    named_hosts: tuple[str, ...]
    # The public content as Jev reads it: code, inputs without secret values, filters, mappings and masking.
    config: dict[str, JsonValue]
    config_truncated: bool
    classification: Classification


@frozen
class HistoryEntry:
    activity: str
    at: datetime
    changed_fields: tuple[str, ...] = ()
    code: str | None = None
    enabled: bool | None = None
    # A test that sent real requests records the origins it reached, with secret values already redacted.
    request_origins: tuple[str, ...] | None = None
    mocked_async_functions: bool | None = None


@frozen
class AccountFacts:
    age_days: int
    minutes_from_signup_to_save: int
    has_active_subscription: bool | None
    member_count: int
    team_count: int
    cdp_trust_score: int | None
    tier: str


@frozen
class OrgFunction:
    name: str | None
    type: str | None
    template_id: str | None
    code_modified_from_template: bool | None
    enabled: bool
    deleted: bool
    created_at: datetime
    updated_at: datetime
    named_hosts: tuple[str, ...]
    rule_hits: tuple[str, ...]


@frozen
class CaseFile:
    function: FunctionUnderReview
    account: AccountFacts
    # Oldest first. Entries before these are left out, and `history_omitted` counts them.
    history: tuple[HistoryEntry, ...]
    history_omitted: int
    # The other functions of the organization, last updated first, deleted and disabled ones included.
    org_functions: tuple[OrgFunction, ...]
    org_functions_omitted: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"), default=_json_default)


def build_case_file(hog_function: HogFunction, scored: ScoredHogFunction) -> CaseFile:
    team = hog_function.team
    history = _history(hog_function)
    org_functions = _org_functions(hog_function)
    return _fit(
        CaseFile(
            function=_function_under_review(hog_function, scored),
            account=_account_facts(hog_function, team, scored),
            history=history.entries,
            history_omitted=history.omitted,
            org_functions=org_functions.entries,
            org_functions_omitted=org_functions.omitted,
        )
    )


def _function_under_review(hog_function: HogFunction, scored: ScoredHogFunction) -> FunctionUnderReview:
    content = content_of(hog_function, hog_function.template)
    config, truncated = build_state(content)
    verdict = scored.verdict
    return FunctionUnderReview(
        name=hog_function.name,
        type=hog_function.type,
        template_id=hog_function.template_id,
        code_modified_from_template=content.code_modified_from_template,
        enabled=hog_function.enabled,
        created_at=hog_function.created_at,
        saved_at=hog_function.updated_at,
        named_hosts=rules.named_hosts(content)[:MAX_HOSTS_PER_FUNCTION],
        config=config,
        config_truncated=truncated,
        classification=Classification(
            rule_hits=tuple(rule.value for rule in scored.rule_hits),
            scores=None if verdict is None else dict(verdict.scores),
            risk_score=None if verdict is None else verdict.risk_score,
            would_alert=scored.would_alert,
            would_block=scored.would_block,
            set_aside_scores={question: reason.value for question, reason in scored.set_aside.items()},
            model_alert_gates=() if verdict is None else tuple(gate.value for gate in verdict.model_alert_gates),
            outbound_call=scored.outbound_call,
            failure=None if scored.failure is None else scored.failure.value,
        ),
    )


def _account_facts(hog_function: HogFunction, team: Team, scored: ScoredHogFunction) -> AccountFacts:
    organization = team.organization
    return AccountFacts(
        age_days=scored.account.age.days,
        minutes_from_signup_to_save=int((hog_function.updated_at - organization.created_at).total_seconds() // 60),
        has_active_subscription=scored.account.has_active_subscription,
        member_count=scored.account.member_count,
        team_count=Team.objects.filter(organization_id=organization.id).count(),
        cdp_trust_score=scored.account.cdp_trust_score,
        tier=scored.account_tier.value,
    )


@frozen
class _History:
    entries: tuple[HistoryEntry, ...]
    omitted: int


def _history(hog_function: HogFunction) -> _History:
    logged = ActivityLog.objects.filter(team_id=hog_function.team_id, scope="HogFunction", item_id=str(hog_function.id))
    total = logged.count()
    latest = list(logged.order_by("-created_at").only("activity", "created_at", "detail")[:MAX_HISTORY_ENTRIES])
    return _History(
        entries=tuple(_history_entry(row) for row in reversed(latest)),
        omitted=max(total - MAX_HISTORY_ENTRIES, 0),
    )


def _history_entry(row: ActivityLog) -> HistoryEntry:
    detail = row.detail if isinstance(row.detail, dict) else {}
    changes = [change for change in detail.get("changes") or [] if isinstance(change, dict)]
    new_values = {
        change["field"]: change.get("after") for change in changes if change.get("field") in _HISTORY_VALUE_FIELDS
    }
    context = detail.get("context") if row.activity == "tested" else None
    test = context if isinstance(context, dict) else {}
    code = test.get("hog") if test else new_values.get("hog")
    enabled = new_values.get("enabled")
    origins = test.get("request_origins")
    mocked = test.get("mock_async_functions")
    return HistoryEntry(
        activity=row.activity,
        at=row.created_at,
        changed_fields=tuple(str(change.get("field")) for change in changes if change.get("field")),
        code=_cut(code, MAX_HISTORY_CODE_CHARS) if isinstance(code, str) else None,
        enabled=enabled if isinstance(enabled, bool) else None,
        request_origins=tuple(str(origin) for origin in origins) if isinstance(origins, list) else None,
        mocked_async_functions=mocked if isinstance(mocked, bool) else None,
    )


@frozen
class _OrgFunctions:
    entries: tuple[OrgFunction, ...]
    omitted: int


def _org_functions(hog_function: HogFunction) -> _OrgFunctions:
    # Scoped to the organization, not the team: a probe often spreads its attempts over several projects.
    others = HogFunction.objects.filter(team__organization_id=hog_function.team.organization_id).exclude(
        pk=hog_function.pk
    )
    total = others.count()
    latest = others.select_related("hog_function_template").order_by("-updated_at")[:MAX_ORG_FUNCTIONS]
    return _OrgFunctions(
        entries=tuple(_org_function(other) for other in latest), omitted=max(total - MAX_ORG_FUNCTIONS, 0)
    )


def _org_function(hog_function: HogFunction) -> OrgFunction:
    # The linked template only, so the list costs no query per function. Secret inputs stay out of the rules too.
    content = content_of(hog_function, hog_function.hog_function_template)
    return OrgFunction(
        name=hog_function.name,
        type=hog_function.type,
        template_id=hog_function.template_id,
        code_modified_from_template=content.code_modified_from_template,
        enabled=hog_function.enabled,
        deleted=hog_function.deleted,
        created_at=hog_function.created_at,
        updated_at=hog_function.updated_at,
        named_hosts=rules.named_hosts(content)[:MAX_HOSTS_PER_FUNCTION],
        rule_hits=tuple(rule.value for rule in rules.matched_rules(content)),
    )


def _fit(case_file: CaseFile) -> CaseFile:
    """Drop the oldest history, then the least recently updated functions of the organization, until the case
    file fits. The function under review is capped on its own by `build_state`, so it always stays."""
    while len(case_file.to_json()) > MAX_CASE_FILE_CHARS:
        if case_file.history:
            case_file = replace(case_file, history=case_file.history[1:], history_omitted=case_file.history_omitted + 1)
        elif case_file.org_functions:
            case_file = replace(
                case_file,
                org_functions=case_file.org_functions[:-1],
                org_functions_omitted=case_file.org_functions_omitted + 1,
            )
        else:
            break
    return case_file


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - len(_TRUNCATED_MARKER)] + _TRUNCATED_MARKER


def _json_default(value: object) -> JsonValue:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
