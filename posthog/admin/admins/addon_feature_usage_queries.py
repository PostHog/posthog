"""Add-on feature adoption metrics, segmented by an org's current add-on.

Each org is classified into exactly one add-on cohort (Enterprise > Scale >
Boost > Paid > Free) by matching its synced `Organization.available_product_features`
against the tier-exclusive feature keys defined below. Add-ons stack, so a Scale
org has every Boost feature too — usage of each feature is therefore reported for
every cohort that includes it (a Boost feature shows adoption across the Boost,
Scale and Enterprise cohorts).

Entitlement comes from `available_product_features`, which the billing service
keeps in sync, so no cross-service call is needed. Usage is read from the backing
model each feature writes to — all Postgres, no events.

Every metric runs as its own small, time-boxed query and is fault-isolated: if
one query times out or errors, the rest still render. Some backing tables are
very large, so a single slow scan must not take the whole page down.
"""

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

from django.db import connection, transaction

logger = logging.getLogger(__name__)

# Per-query ceiling. A metric that blows past this is reported as failed rather
# than allowed to hold the request (and a Postgres connection) open.
DEFAULT_TIMEOUT_MS = 45_000

# Tier-exclusive feature keys (from the billing add-on definitions). Presence of
# any key in a set implies the org is on at least that tier. `access_control` /
# `advanced_permissions` are intentionally NOT used to classify — they are
# propagating to all plans, so they would be a noisy signal — but they are still
# reported as Boost features in the usage breakdown below.
ENTERPRISE_SIGNAL_KEYS = ["role_based_access", "scim"]
SCALE_SIGNAL_KEYS = ["saml", "managed_reverse_proxy", "audit_logs", "product_analytics_ai", "approvals"]
BOOST_SIGNAL_KEYS = [
    "white_labelling",
    "data_color_themes",
    "sso_enforcement",
    "2fa_enforcement",
    "automatic_provisioning",
    "organization_invite_settings",
    "organization_security_settings",
]

# Add-on cohorts that carry feature usage, lowest to highest. `paid` and `free`
# have no add-on and so no feature sections.
TIER_ORDER = ["boost", "scale", "enterprise"]
TIER_LABELS = {
    "boost": "Boost",
    "scale": "Scale",
    "enterprise": "Enterprise",
    "paid": "Paid (no add-on)",
    "free": "Free",
}

# Classifies every org into one tier. Highest matching tier wins.
_ORG_TIER_CTE = """
org_tier AS (
    SELECT o.id,
        CASE
            WHEN ff.ks && %(ent)s::text[] THEN 'enterprise'
            WHEN ff.ks && %(scale)s::text[] THEN 'scale'
            WHEN ff.ks && %(boost)s::text[] THEN 'boost'
            WHEN cardinality(ff.ks) > 0 THEN 'paid'
            ELSE 'free'
        END AS tier
    FROM posthog_organization o
    CROSS JOIN LATERAL (
        SELECT array(SELECT e->>'key' FROM unnest(o.available_product_features) AS e) AS ks
    ) ff
)
"""

_TIER_PARAMS = {"ent": ENTERPRISE_SIGNAL_KEYS, "scale": SCALE_SIGNAL_KEYS, "boost": BOOST_SIGNAL_KEYS}

# A bucket is (label, low, high). `high=None` means open-ended (>= low).
# The (label, 0, 0) bucket counts cohort orgs with no usage at all.
Bucket = tuple[str, int, Optional[int]]

COUNT_BUCKETS_WIDE: list[Bucket] = [("0", 0, 0), ("1", 1, 1), ("2–10", 2, 10), ("11+", 11, None)]
COUNT_BUCKETS_MID: list[Bucket] = [("0", 0, 0), ("1", 1, 1), ("2–5", 2, 5), ("6+", 6, None)]
COUNT_BUCKETS_SMALL: list[Bucket] = [("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3+", 3, None)]
COUNT_BUCKETS_TINY: list[Bucket] = [("0", 0, 0), ("1", 1, 1), ("2+", 2, None)]


def _applicable_tiers(home_tier: str) -> list[str]:
    """The home tier and every higher tier (features stack upward)."""
    return TIER_ORDER[TIER_ORDER.index(home_tier) :]


@dataclass
class BucketResult:
    label: str
    count: int
    pct: float


@dataclass
class TierMetric:
    """One feature's usage within one add-on cohort."""

    tier: str
    cohort_n: int = 0  # orgs in this cohort (the denominator; all are entitled)
    used: int = 0  # orgs with any usage (count) or with the setting on (bool)
    buckets: list[BucketResult] = field(default_factory=list)

    @property
    def adoption_pct(self) -> float:
        return round(100 * self.used / self.cohort_n, 1) if self.cohort_n else 0.0


@dataclass
class FeatureMetric:
    key: str
    label: str
    home_tier: str
    kind: Literal["count", "bool", "projects", "entitlement_only"]
    note: str = ""
    error: str = ""
    by_tier: dict[str, TierMetric] = field(default_factory=dict)

    @property
    def applicable_tiers(self) -> list[str]:
        return _applicable_tiers(self.home_tier)


def _run(sql: str, params: dict, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> list[tuple]:
    """Run a read-only query under a LOCAL statement timeout.

    The timeout is LOCAL to an atomic block, so it resets automatically on exit
    even when the query raises (e.g. on timeout), leaving the connection clean.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
            cursor.execute(sql, params)
            return cursor.fetchall()


def _bucket_filters(buckets: list[Bucket]) -> str:
    parts = []
    for i, (_label, lo, hi) in enumerate(buckets):
        if lo == 0 and hi == 0:
            cond = "coalesce(u.c, 0) = 0"
        elif hi is None:
            cond = f"u.c >= {lo}"
        else:
            cond = f"u.c BETWEEN {lo} AND {hi}"
        parts.append(f"count(*) FILTER (WHERE {cond}) AS b{i}")
    return ",\n           ".join(parts)


def _empty_by_tier(tiers: list[str], buckets: Optional[list[Bucket]] = None) -> dict[str, TierMetric]:
    out = {}
    for t in tiers:
        tm = TierMetric(tier=t)
        if buckets is not None:
            tm.buckets = [BucketResult(label=label, count=0, pct=0.0) for label, _lo, _hi in buckets]
        out[t] = tm
    return out


def _count_metric(spec: "CountSpec") -> FeatureMetric:
    tiers = _applicable_tiers(spec.home_tier)
    result = FeatureMetric(key=spec.key, label=spec.label, home_tier=spec.home_tier, kind="count", note=spec.note)
    result.by_tier = _empty_by_tier(tiers, spec.buckets)
    sql = f"""
    WITH {_ORG_TIER_CTE},
    usage AS (
        {spec.usage_sql}
    )
    SELECT ot.tier,
           count(*) AS cohort_n,
           count(u.org_id) AS used,
           {_bucket_filters(spec.buckets)}
    FROM org_tier ot
    LEFT JOIN usage u ON u.org_id = ot.id
    WHERE ot.tier = ANY(%(tiers)s)
    GROUP BY ot.tier
    """
    try:
        rows = _run(sql, {**_TIER_PARAMS, "tiers": tiers})
    except Exception as e:
        logger.warning("addon usage metric %s failed: %s", spec.key, e)
        result.error = str(e)
        return result

    for row in rows:
        tier, cohort_n, used = row[0], row[1] or 0, row[2] or 0
        tm = TierMetric(tier=tier, cohort_n=cohort_n, used=used)
        for i, (label, _lo, _hi) in enumerate(spec.buckets):
            count = row[3 + i] or 0
            pct = round(100 * count / cohort_n, 1) if cohort_n else 0.0
            tm.buckets.append(BucketResult(label=label, count=count, pct=pct))
        result.by_tier[tier] = tm
    return result


def _bool_metric(spec: "BoolSpec") -> FeatureMetric:
    tiers = _applicable_tiers(spec.home_tier)
    result = FeatureMetric(key=spec.key, label=spec.label, home_tier=spec.home_tier, kind="bool", note=spec.note)
    result.by_tier = _empty_by_tier(tiers)
    # domain_condition / team_condition aggregate a child table up to the org
    # (an org "uses" the feature if any verified domain / any team qualifies).
    if spec.domain_condition:
        agg = f"""agg AS (
            SELECT d.organization_id AS org_id, bool_or({spec.domain_condition}) AS flag
            FROM posthog_organizationdomain d
            WHERE d.verified_at IS NOT NULL
            GROUP BY d.organization_id
        )"""
    elif spec.team_condition:
        agg = f"""agg AS (
            SELECT te.organization_id AS org_id, bool_or({spec.team_condition}) AS flag
            FROM posthog_team te
            GROUP BY te.organization_id
        )"""
    else:
        agg = ""

    if agg:
        sql = f"""
        WITH {_ORG_TIER_CTE},
        {agg}
        SELECT ot.tier,
               count(*) AS cohort_n,
               count(*) FILTER (WHERE coalesce(a.flag, false)) AS used
        FROM org_tier ot
        LEFT JOIN agg a ON a.org_id = ot.id
        WHERE ot.tier = ANY(%(tiers)s)
        GROUP BY ot.tier
        """
    else:
        sql = f"""
        WITH {_ORG_TIER_CTE}
        SELECT ot.tier,
               count(*) AS cohort_n,
               count(*) FILTER (WHERE {spec.org_condition}) AS used
        FROM org_tier ot
        JOIN posthog_organization o ON o.id = ot.id
        WHERE ot.tier = ANY(%(tiers)s)
        GROUP BY ot.tier
        """
    try:
        rows = _run(sql, {**_TIER_PARAMS, "tiers": tiers})
    except Exception as e:
        logger.warning("addon usage metric %s failed: %s", spec.key, e)
        result.error = str(e)
        return result
    for tier, cohort_n, used in rows:
        result.by_tier[tier] = TierMetric(tier=tier, cohort_n=cohort_n or 0, used=used or 0)
    return result


def _entitlement_only_metric(spec: "EntitlementOnlySpec") -> FeatureMetric:
    tiers = _applicable_tiers(spec.home_tier)
    result = FeatureMetric(
        key=spec.key, label=spec.label, home_tier=spec.home_tier, kind="entitlement_only", note=spec.note
    )
    result.by_tier = _empty_by_tier(tiers)
    sql = f"""
    WITH {_ORG_TIER_CTE}
    SELECT ot.tier, count(*) AS cohort_n
    FROM org_tier ot
    WHERE ot.tier = ANY(%(tiers)s)
    GROUP BY ot.tier
    """
    try:
        rows = _run(sql, {**_TIER_PARAMS, "tiers": tiers})
    except Exception as e:
        logger.warning("addon usage metric %s failed: %s", spec.key, e)
        result.error = str(e)
        return result
    for tier, cohort_n in rows:
        result.by_tier[tier] = TierMetric(tier=tier, cohort_n=cohort_n or 0)
    return result


@dataclass
class CountSpec:
    key: str
    label: str
    home_tier: str
    usage_sql: str  # must SELECT (org_id, c)
    buckets: list[Bucket]
    note: str = ""

    def run(self) -> FeatureMetric:
        return _count_metric(self)


@dataclass
class BoolSpec:
    key: str
    label: str
    home_tier: str
    org_condition: str = ""  # predicate on posthog_organization `o`
    domain_condition: str = ""  # predicate on a verified posthog_organizationdomain `d`
    team_condition: str = ""  # predicate on a posthog_team `te`
    note: str = ""

    def run(self) -> FeatureMetric:
        return _bool_metric(self)


# Project-limit buckets: how each org's project count sits against its
# entitlement limit (null limit = unlimited).
PROJECT_BUCKET_LABELS = ["unlimited", "under limit", "at limit", "over limit"]


def _projects_metric(spec: "ProjectsSpec") -> FeatureMetric:
    tiers = _applicable_tiers(spec.home_tier)
    result = FeatureMetric(key=spec.key, label=spec.label, home_tier=spec.home_tier, kind="projects", note=spec.note)
    result.by_tier = {
        t: TierMetric(tier=t, buckets=[BucketResult(label=label, count=0, pct=0.0) for label in PROJECT_BUCKET_LABELS])
        for t in tiers
    }
    sql = f"""
    WITH {_ORG_TIER_CTE},
    proj AS (
        SELECT organization_id AS org_id, count(DISTINCT project_id) AS c
        FROM posthog_team
        WHERE NOT coalesce(is_demo, false)
        GROUP BY organization_id
    ),
    lim AS (
        SELECT o.id AS org_id,
            (SELECT (e->>'limit')::int
             FROM unnest(o.available_product_features) AS e
             WHERE e->>'key' = 'organizations_projects' LIMIT 1) AS limit_n
        FROM posthog_organization o
    )
    SELECT ot.tier,
           count(*) AS cohort_n,
           count(*) FILTER (WHERE l.limit_n IS NULL) AS unlimited,
           count(*) FILTER (WHERE l.limit_n IS NOT NULL AND coalesce(p.c, 0) < l.limit_n) AS under_limit,
           count(*) FILTER (WHERE l.limit_n IS NOT NULL AND coalesce(p.c, 0) = l.limit_n) AS at_limit,
           count(*) FILTER (WHERE l.limit_n IS NOT NULL AND coalesce(p.c, 0) > l.limit_n) AS over_limit
    FROM org_tier ot
    JOIN lim l ON l.org_id = ot.id
    LEFT JOIN proj p ON p.org_id = ot.id
    WHERE ot.tier = ANY(%(tiers)s)
    GROUP BY ot.tier
    """
    try:
        rows = _run(sql, {**_TIER_PARAMS, "tiers": tiers})
    except Exception as e:
        logger.warning("addon usage metric %s failed: %s", spec.key, e)
        result.error = str(e)
        return result
    for row in rows:
        tier, cohort_n = row[0], row[1] or 0
        counts = [row[2] or 0, row[3] or 0, row[4] or 0, row[5] or 0]
        tm = TierMetric(tier=tier, cohort_n=cohort_n)
        # "used" = orgs at or over their project entitlement (capacity pressure)
        tm.used = counts[2] + counts[3]
        tm.buckets = [
            BucketResult(label=label, count=c, pct=round(100 * c / cohort_n, 1) if cohort_n else 0.0)
            for label, c in zip(PROJECT_BUCKET_LABELS, counts)
        ]
        result.by_tier[tier] = tm
    return result


@dataclass
class ProjectsSpec:
    key: str
    label: str
    home_tier: str
    note: str = ""

    def run(self) -> FeatureMetric:
        return _projects_metric(self)


@dataclass
class EntitlementOnlySpec:
    key: str
    label: str
    home_tier: str
    note: str = ""

    def run(self) -> FeatureMetric:
        return _entitlement_only_metric(self)


# Usage subqueries. Team-scoped models aggregate up to the org via posthog_team.
_USAGE_ACCESS_CONTROL = """
    SELECT t.organization_id AS org_id, count(*) AS c
    FROM ee_accesscontrol x
    JOIN posthog_team t ON t.id = x.team_id
    GROUP BY t.organization_id
"""
_USAGE_DATA_COLOR_THEME = """
    SELECT t.organization_id AS org_id, count(*) AS c
    FROM posthog_datacolortheme x
    JOIN posthog_team t ON t.id = x.team_id
    WHERE x.team_id IS NOT NULL AND coalesce(x.deleted, false) = false
    GROUP BY t.organization_id
"""
_USAGE_WHITELABEL = """
    SELECT t.organization_id AS org_id, count(*) AS c
    FROM posthog_sharingconfiguration x
    JOIN posthog_team t ON t.id = x.team_id
    WHERE x.enabled AND x.settings ? 'whitelabel' AND x.settings->>'whitelabel' = 'true'
    GROUP BY t.organization_id
"""
_USAGE_CONVERSATIONS = """
    SELECT t.organization_id AS org_id, count(*) AS c
    FROM ee_conversation x
    JOIN posthog_team t ON t.id = x.team_id
    GROUP BY t.organization_id
"""
_USAGE_ROLES = """
    SELECT x.organization_id AS org_id, count(*) AS c
    FROM ee_role x
    GROUP BY x.organization_id
"""
_USAGE_APPROVAL_POLICIES = """
    SELECT x.organization_id AS org_id, count(*) AS c
    FROM posthog_approvalpolicy x
    WHERE x.enabled
    GROUP BY x.organization_id
"""
_USAGE_PROXY = """
    SELECT x.organization_id AS org_id, count(*) AS c
    FROM posthog_proxyrecord x
    GROUP BY x.organization_id
"""
# No dedicated feature gate — proxied by enabled shared resources that carry a
# custom settings object (whitelabel, hidden header, etc.).
_USAGE_SHARED_RESOURCE_CONFIGS = """
    SELECT t.organization_id AS org_id, count(*) AS c
    FROM posthog_sharingconfiguration x
    JOIN posthog_team t ON t.id = x.team_id
    WHERE x.enabled AND x.settings IS NOT NULL AND x.settings <> '{}'::jsonb
    GROUP BY t.organization_id
"""


# `home_tier` is the add-on that introduces the feature; higher cohorts inherit
# it. Each metric is reported across every cohort in its applicable tiers.
METRIC_SPECS: list = [
    # Boost — security & branding tier
    BoolSpec(key="2fa_enforcement", label="2FA enforcement", home_tier="boost", org_condition="o.enforce_2fa IS TRUE"),
    BoolSpec(
        key="sso_enforcement",
        label="SSO enforcement",
        home_tier="boost",
        domain_condition="d.sso_enforcement <> ''",
        note="≥1 verified domain with SSO enforcement set.",
    ),
    BoolSpec(
        key="automatic_provisioning",
        label="Automatic provisioning (JIT)",
        home_tier="boost",
        domain_condition="d.jit_provisioning_enabled IS TRUE",
        note="≥1 verified domain with JIT provisioning.",
    ),
    BoolSpec(
        key="organization_invite_settings",
        label="Restricted member invites",
        home_tier="boost",
        org_condition="o.members_can_invite IS FALSE",
        note="Members-can-invite turned off (non-default).",
    ),
    BoolSpec(
        key="organization_security_settings",
        label="Org security settings tightened",
        home_tier="boost",
        org_condition="o.members_can_use_personal_api_keys IS FALSE OR o.allow_publicly_shared_resources IS FALSE",
        note="Personal API keys or public sharing restricted (non-default).",
    ),
    CountSpec(
        key="access_control",
        label="Access control rules",
        home_tier="boost",
        usage_sql=_USAGE_ACCESS_CONTROL,
        buckets=COUNT_BUCKETS_WIDE,
        note="advanced_permissions shares the same backing model. Not used to classify cohorts (propagating to all plans).",
    ),
    CountSpec(
        key="white_labelling",
        label="White-labelled shares",
        home_tier="boost",
        usage_sql=_USAGE_WHITELABEL,
        buckets=COUNT_BUCKETS_MID,
    ),
    CountSpec(
        key="data_color_themes",
        label="Custom chart color themes",
        home_tier="boost",
        usage_sql=_USAGE_DATA_COLOR_THEME,
        buckets=COUNT_BUCKETS_MID,
    ),
    ProjectsSpec(
        key="organizations_projects",
        label="Projects vs. entitlement limit",
        home_tier="boost",
        note="Non-demo projects per org compared to the org's project limit (null limit = unlimited).",
    ),
    CountSpec(
        key="shared_resource_configurations",
        label="Configured shared resources",
        home_tier="boost",
        usage_sql=_USAGE_SHARED_RESOURCE_CONFIGS,
        buckets=COUNT_BUCKETS_MID,
        note="Proxy: enabled shared resources with a custom settings object (no dedicated feature gate).",
    ),
    BoolSpec(
        key="session_replay_data_retention",
        label="Extended replay retention",
        home_tier="boost",
        team_condition="te.session_recording_retention_period <> '30d'",
        note="≥1 team with retention beyond the 30-day default (90d / 1y / 5y).",
    ),
    # Scale — scale-up tier
    BoolSpec(
        key="saml",
        label="SAML configured",
        home_tier="scale",
        domain_condition="d.saml_entity_id <> '' AND d.saml_acs_url <> '' AND coalesce(d.saml_x509_cert, '') <> ''",
        note="≥1 verified domain with full SAML config.",
    ),
    CountSpec(
        key="managed_reverse_proxy",
        label="Managed reverse proxies",
        home_tier="scale",
        usage_sql=_USAGE_PROXY,
        buckets=COUNT_BUCKETS_TINY,
    ),
    CountSpec(
        key="approvals",
        label="Approval policies",
        home_tier="scale",
        usage_sql=_USAGE_APPROVAL_POLICIES,
        buckets=COUNT_BUCKETS_SMALL,
    ),
    CountSpec(
        key="product_analytics_ai",
        label="Max AI conversations",
        home_tier="scale",
        usage_sql=_USAGE_CONVERSATIONS,
        buckets=COUNT_BUCKETS_WIDE,
    ),
    EntitlementOnlySpec(
        key="audit_logs",
        label="Activity logs",
        home_tier="scale",
        note="Always-on; no per-org usage signal (activity logs are written regardless of plan).",
    ),
    # Enterprise — enterprise tier
    CountSpec(
        key="role_based_access",
        label="RBAC roles",
        home_tier="enterprise",
        usage_sql=_USAGE_ROLES,
        buckets=COUNT_BUCKETS_MID,
    ),
    BoolSpec(
        key="scim",
        label="SCIM enabled",
        home_tier="enterprise",
        domain_condition="d.scim_enabled IS TRUE",
        note="≥1 verified domain with SCIM enabled.",
    ),
]


# Add-on feature keys deliberately left out of the usage breakdown because they
# have no measurable product signal — commercial/legal terms, human support
# services, and compliance artifacts. Shown at the bottom of the page for
# completeness.
EXCLUDED_KEYS: list[tuple[str, str]] = [
    ("hipaa_baa", "Compliance — a signed BAA, not a product action"),
    ("priority_support", "Support SLA — human service"),
    ("support_response_time", "Support SLA — human service"),
    ("dedicated_support", "Support — dedicated account manager"),
    ("configuration_support", "Support — personalized onboarding"),
    ("training", "Support — onboarding/training"),
    ("security_assessment", "Compliance — SOC 2 / pentest review"),
    ("terms_and_conditions", "Legal/commercial — MSA"),
    ("bespoke_pricing", "Commercial — custom pricing"),
    ("invoice_payments", "Commercial — pay by invoice"),
    (
        "organization_app_query_concurrency_limit",
        "Platform query-concurrency limit — entitlement only, no adoption signal",
    ),
]


@dataclass
class CohortSummary:
    counts: dict[str, int] = field(default_factory=dict)  # tier -> org count
    error: str = ""

    def get(self, tier: str) -> int:
        return self.counts.get(tier, 0)


def _run_cohort_summary() -> CohortSummary:
    summary = CohortSummary()
    sql = f"WITH {_ORG_TIER_CTE} SELECT ot.tier, count(*) FROM org_tier ot GROUP BY ot.tier"
    try:
        for tier, n in _run(sql, _TIER_PARAMS):
            summary.counts[tier] = n or 0
    except Exception as e:
        logger.warning("addon cohort summary failed: %s", e)
        summary.error = str(e)
    return summary


@dataclass
class CohortSection:
    tier: str
    label: str
    size: int
    features: list[FeatureMetric] = field(default_factory=list)


@dataclass
class AddonUsageReport:
    summary: CohortSummary
    sections: list[CohortSection]
    excluded: list[tuple[str, str]]
    failures: int


def build_report() -> AddonUsageReport:
    """Classify orgs into add-on cohorts and report feature usage within each.

    No metric failure aborts the rest — failures are surfaced per-metric.
    """
    summary = _run_cohort_summary()

    metrics = [spec.run() for spec in METRIC_SPECS]
    failures = sum(1 for m in metrics if m.error)

    # Build one section per add-on cohort, listing the features that cohort is
    # entitled to (its tier plus everything inherited from lower tiers).
    sections: list[CohortSection] = []
    for tier in TIER_ORDER:
        section = CohortSection(tier=tier, label=TIER_LABELS[tier], size=summary.get(tier))
        section.features = [m for m in metrics if tier in m.applicable_tiers]
        sections.append(section)

    return AddonUsageReport(summary=summary, sections=sections, excluded=EXCLUDED_KEYS, failures=failures)
