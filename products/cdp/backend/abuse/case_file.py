"""The case file a frontier model reviews for a severe save: the function, its recent edit and test history, the
account, and counts of the organization's other functions.

Built from Postgres only, bounded in size, and without secret input values.
"""

import json
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime
from urllib.parse import urlsplit

from django.db.models import Count, Q

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.cdp.backend.abuse import rules
from products.cdp.backend.abuse.classifier import HogFunctionContent, build_state
from products.cdp.backend.abuse.shadow import ScoredHogFunction, _with_secret_inputs, content_of
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.destination_test_runs import redact_secrets_in_origins, stored_secret_values
from products.ml_inference.backend.facade.contracts import JsonValue

MAX_HISTORY_ENTRIES = 10
MAX_ORG_FUNCTIONS_CHECKED = 50
MAX_HOSTS_PER_FUNCTION = 20
MAX_RULE_EVIDENCE = 20
UNLOCATED = "not explained by the public content: depends on a secret input"
MAX_HISTORY_CODE_CHARS = 4_000
MAX_ORIGINS_PER_TEST = 20
MAX_ORIGIN_CHARS = 300
# Room for the function's config, which `build_state` caps at the Jev state limit, and a short history.
MAX_CASE_FILE_CHARS = 100_000
_TRUNCATED_MARKER = " [truncated]"
# Only these fields of an update show their new value. The activity log masks the inputs, but not every field that
# can hold a secret: the default of a secret input sits unmasked in the inputs schema.
_HISTORY_VALUE_FIELDS = frozenset({"hog", "enabled"})


@frozen
class Classification:
    rule_hits: tuple[str, ...]
    # Where each rule hit matched, with at least one entry for every hit before the cap. A hit that the public
    # content does not explain depends on a secret input, so it shows `UNLOCATED` and no host, and the value stays out.
    rule_evidence: tuple[rules.RuleEvidence, ...]
    rule_evidence_omitted: int
    # The hosts the rules count as request targets.
    request_hosts: tuple[str, ...]
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
    # Hosts that a rule flags come first.
    named_hosts: tuple[str, ...]
    named_hosts_omitted: int
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
    # A test that sent real requests records the origins it reached. Redacted again against the secrets stored now,
    # because the row only redacts the secrets that were stored when the test ran.
    # Origins that a rule flags come first.
    request_origins: tuple[str, ...] | None = None
    request_origins_omitted: int = 0
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
class OrgFunctionCounts:
    """The organization's other functions, across all its projects."""

    total: int
    deleted: int
    # Not deleted, and not enabled.
    disabled: int
    # Rule hits are matched on the most recently updated functions only, with their secret inputs like a save is.
    checked_for_rules: int
    # How many of the checked functions hit each rule.
    rule_hits: dict[str, int]


@frozen
class CaseFile:
    function: FunctionUnderReview
    account: AccountFacts
    # Oldest first. Entries before these are left out, and `history_omitted` counts them.
    history: tuple[HistoryEntry, ...]
    history_omitted: int
    org_functions: OrgFunctionCounts

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"), default=_json_default)


def build_case_file(hog_function: HogFunction, scored: ScoredHogFunction) -> CaseFile:
    team = hog_function.team
    history = _history(hog_function)
    return _fit(
        CaseFile(
            function=_function_under_review(hog_function, scored),
            account=_account_facts(hog_function, team, scored),
            history=history.entries,
            history_omitted=history.omitted,
            org_functions=_org_function_counts(hog_function),
        )
    )


def _function_under_review(hog_function: HogFunction, scored: ScoredHogFunction) -> FunctionUnderReview:
    content = content_of(hog_function, hog_function.template)
    config, truncated = build_state(content)
    hosts = _named_hosts(content)
    evidence = _rule_evidence(content, scored.rule_hits)
    verdict = scored.verdict
    return FunctionUnderReview(
        name=hog_function.name,
        type=hog_function.type,
        template_id=hog_function.template_id,
        code_modified_from_template=content.code_modified_from_template,
        enabled=hog_function.enabled,
        created_at=hog_function.created_at,
        saved_at=hog_function.updated_at,
        named_hosts=hosts.shown,
        named_hosts_omitted=hosts.omitted,
        config=config,
        config_truncated=truncated,
        classification=Classification(
            rule_hits=tuple(rule.value for rule in scored.rule_hits),
            rule_evidence=evidence[:MAX_RULE_EVIDENCE],
            rule_evidence_omitted=max(len(evidence) - MAX_RULE_EVIDENCE, 0),
            request_hosts=rules.request_hosts(content)[:MAX_HOSTS_PER_FUNCTION],
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


def _rule_evidence(content: HogFunctionContent, rule_hits: tuple[rules.Rule, ...]) -> tuple[rules.RuleEvidence, ...]:
    public = tuple(entry for entry in rules.rule_evidence(content) if entry.rule in rule_hits)
    explained = {entry.rule for entry in public}
    secret_only = tuple(
        rules.RuleEvidence(rule=rule, location=UNLOCATED, host=None, request_target=False)
        for rule in rule_hits
        if rule not in explained
    )
    return _each_rule_first(public + secret_only)


def _each_rule_first(evidence: tuple[rules.RuleEvidence, ...]) -> tuple[rules.RuleEvidence, ...]:
    """The first entry of each rule, then the rest in order, so the cap never drops every entry of a hit."""
    first: dict[rules.Rule, rules.RuleEvidence] = {}
    for entry in evidence:
        first.setdefault(entry.rule, entry)
    leading = tuple(first.values())
    return leading + tuple(entry for entry in evidence if entry not in leading)


def _account_facts(hog_function: HogFunction, team: Team, scored: ScoredHogFunction) -> AccountFacts:
    organization = team.organization
    return AccountFacts(
        age_days=scored.account.age.days,
        minutes_from_signup_to_save=max(
            int((hog_function.updated_at - organization.created_at).total_seconds() // 60), 0
        ),
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
    rows = list(reversed(latest))
    secrets = stored_secret_values(
        hog_function.team_id,
        _tested_integration_ids(rows),
        [hog_function.encrypted_inputs, hog_function.draft_encrypted_inputs],
    )
    return _History(
        entries=tuple(_history_entry(row, secrets) for row in rows),
        omitted=max(total - MAX_HISTORY_ENTRIES, 0),
    )


def _tested_integration_ids(rows: list[ActivityLog]) -> list[int]:
    ids: set[int] = set()
    for row in rows:
        listed = _test_context(row).get("integration_ids")
        if isinstance(listed, list):
            ids.update(value for value in listed if isinstance(value, int) and not isinstance(value, bool))
    return sorted(ids)


def _test_context(row: ActivityLog) -> dict[str, JsonValue]:
    detail = row.detail if isinstance(row.detail, dict) else {}
    context = detail.get("context") if row.activity == "tested" else None
    return context if isinstance(context, dict) else {}


def _history_entry(row: ActivityLog, secrets: list[str]) -> HistoryEntry:
    detail = row.detail if isinstance(row.detail, dict) else {}
    changes = [change for change in detail.get("changes") or [] if isinstance(change, dict)]
    new_values = {
        change["field"]: change.get("after") for change in changes if change.get("field") in _HISTORY_VALUE_FIELDS
    }
    test = _test_context(row)
    code = test.get("hog") if test else new_values.get("hog")
    enabled = new_values.get("enabled")
    origins = test.get("request_origins")
    shown_origins = _redacted_origins(origins, secrets) if isinstance(origins, list) else None
    mocked = test.get("mock_async_functions")
    return HistoryEntry(
        activity=row.activity,
        at=row.created_at,
        changed_fields=tuple(str(change.get("field")) for change in changes if change.get("field")),
        code=_cut(code, MAX_HISTORY_CODE_CHARS) if isinstance(code, str) else None,
        enabled=enabled if isinstance(enabled, bool) else None,
        request_origins=shown_origins,
        request_origins_omitted=max(len(origins) - MAX_ORIGINS_PER_TEST, 0) if isinstance(origins, list) else 0,
        mocked_async_functions=mocked if isinstance(mocked, bool) else None,
    )


def _redacted_origins(origins: list[JsonValue], secrets: list[str]) -> tuple[str, ...]:
    # Redacted before the cut: the redactor matches only a whole origin, and a cut can split a secret.
    redacted = redact_secrets_in_origins([str(origin) for origin in origins], secrets)
    ranked = sorted(redacted, key=lambda origin: not rules.is_flagged_host(_origin_host(origin)))
    return tuple(_cut(origin, MAX_ORIGIN_CHARS) for origin in ranked[:MAX_ORIGINS_PER_TEST])


def _org_function_counts(hog_function: HogFunction) -> OrgFunctionCounts:
    # Scoped to the organization, not the team: a probe often spreads its attempts over several projects.
    others = HogFunction.objects.filter(team__organization_id=hog_function.team.organization_id).exclude(
        pk=hog_function.pk
    )
    counts = others.aggregate(
        total_count=Count("id"),
        deleted_count=Count("id", filter=Q(deleted=True)),
        disabled_count=Count("id", filter=Q(deleted=False, enabled=False)),
    )
    recent = list(
        others.select_related("hog_function_template")
        .defer("bytecode", "transpiled", "draft", "draft_encrypted_inputs")
        .order_by("-updated_at")[:MAX_ORG_FUNCTIONS_CHECKED]
    )
    # The linked template only, so the check costs no query per function. Only rule names leave, never values.
    hits = Counter(
        rule.value
        for other in recent
        for rule in rules.matched_rules(_with_secret_inputs(other, content_of(other, other.hog_function_template)))
    )
    return OrgFunctionCounts(
        total=counts["total_count"],
        deleted=counts["deleted_count"],
        disabled=counts["disabled_count"],
        checked_for_rules=len(recent),
        rule_hits=dict(sorted(hits.items())),
    )


@frozen
class _Hosts:
    shown: tuple[str, ...]
    omitted: int


def _named_hosts(content: HogFunctionContent) -> _Hosts:
    hosts = rules.named_hosts(content)
    return _Hosts(shown=hosts[:MAX_HOSTS_PER_FUNCTION], omitted=max(len(hosts) - MAX_HOSTS_PER_FUNCTION, 0))


def _fit(case_file: CaseFile) -> CaseFile:
    """Drop the oldest history until the case file fits. Every other part is bounded on its own, so it stays."""
    while case_file.history and len(case_file.to_json()) > MAX_CASE_FILE_CHARS:
        case_file = replace(case_file, history=case_file.history[1:], history_omitted=case_file.history_omitted + 1)
    return case_file


def _origin_host(origin: str) -> str:
    try:
        return urlsplit(origin).hostname or ""
    except ValueError:
        return ""


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - len(_TRUNCATED_MARKER)] + _TRUNCATED_MARKER


def _json_default(value: object) -> JsonValue:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
