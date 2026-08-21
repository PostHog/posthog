"""Find hog functions and hog flows whose stored secret is a read-back marker, not a credential.

The UI shows a saved secret as `MASKED_SECRET_VALUE` and sends that mask back on a re-save to
mean "keep the stored value". When the two sides of that contract disagree, the mask is what
gets encrypted, the destination starts failing auth against the third party, and the real
credential is gone. Only the owner can restore it, so operators need the list of who to tell.

Hog flows read secrets back as a `{"secret": true}` marker instead of the mask string. Their
save path recovers the stored value, but a marker persisted before that guard shipped is the
same failure: the worker uses the marker object as the credential.

The match cannot be a SQL predicate. `encrypted_inputs` is Fernet-encrypted, and Fernet embeds a
timestamp and a random IV, so the same plaintext produces different ciphertext on every write.
Every candidate row has to be decrypted in Python and inspected.
"""

from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from django.db.models import Model, Q, QuerySet

from posthog.cdp.validation import MASKED_SECRET_VALUE
from posthog.dataclasses import frozen
from posthog.utils import absolute_uri

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

DEFAULT_BATCH_SIZE = 500

# Bounds a fleet-wide sweep so an admin request cannot run unbounded. Callers are told when it
# bites rather than being handed a silently short list.
DEFAULT_MAX_RESULTS = 1000

# Bounds the rows one admin request walks. max_results caps findings only, so a sparse sweep
# would otherwise scan both tables end to end inside the web request and outlive the proxy
# timeout. The management command passes no ceiling — a shell has nothing to time out.
DEFAULT_MAX_SCANNED = 50_000


@frozen
class MaskedSecretFinding:
    organization_id: UUID
    organization_name: str
    team_id: int
    team_name: str
    hog_function_id: UUID
    hog_function_name: str
    hog_function_type: str
    template_id: str
    enabled: bool
    deleted: bool
    updated_at: datetime
    # Input keys only, never their values. The value is believed to be the mask, but a scan that
    # prints secret inputs would leak real credentials the moment that belief is wrong.
    masked_live_inputs: tuple[str, ...]
    masked_draft_inputs: tuple[str, ...]
    configuration_url: str


@frozen
class HogFlowMaskedSecretFinding:
    organization_id: UUID
    organization_name: str
    team_id: int
    team_name: str
    hog_flow_id: UUID
    hog_flow_name: str
    status: str
    enabled: bool
    updated_at: datetime
    # Action-qualified input keys only, never their values — same leak-protection reasoning as
    # MaskedSecretFinding.
    masked_live_inputs: tuple[str, ...]
    masked_draft_inputs: tuple[str, ...]
    configuration_url: str


@frozen
class AffectedOrganization:
    organization_id: UUID
    organization_name: str
    team_ids: tuple[int, ...]
    finding_count: int
    enabled_count: int


@frozen
class MaskedSecretScan:
    findings: tuple[MaskedSecretFinding, ...]
    scanned_count: int
    # True when max_results stopped the sweep before the queryset was exhausted, so there are
    # more affected hog functions than `findings` shows.
    truncated: bool


@frozen
class HogFlowMaskedSecretScan:
    findings: tuple[HogFlowMaskedSecretFinding, ...]
    scanned_count: int
    truncated: bool


def _masked_input_keys(stored: object) -> tuple[str, ...]:
    """Input keys whose stored value is the literal mask.

    A row encrypted under a key we no longer hold comes back as the raw ciphertext string rather
    than a dict, because the field swallows `InvalidToken`. The shape has to be checked, not
    assumed.
    """
    if not isinstance(stored, dict):
        return ()
    return tuple(
        sorted(
            key
            for key, entry in stored.items()
            if isinstance(entry, dict) and entry.get("value") == MASKED_SECRET_VALUE
        )
    )


def _flow_masked_input_keys(stored: object) -> tuple[str, ...]:
    """Action-qualified input keys whose stored entry is a persisted read-back marker.

    Hog flow secrets are keyed action id then input key. An entry is poisoned when it is the
    `{"secret": true}` read-back marker with no value — the save path should have swapped it for
    the stored secret — or when its value is the literal mask string. Same shape caveat as
    `_masked_input_keys`: an undecryptable row reads back as a raw string.
    """
    if not isinstance(stored, dict):
        return ()
    poisoned = []
    for action_id, inputs in stored.items():
        if not isinstance(inputs, dict):
            continue
        for key, entry in inputs.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("value") == MASKED_SECRET_VALUE or (entry.get("secret") and "value" not in entry):
                poisoned.append(f"{action_id}.{key}")
    return tuple(sorted(poisoned))


_M = TypeVar("_M", bound=Model)


def _keyset_batches(queryset: QuerySet[_M], batch_size: int) -> Iterator[_M]:
    """Fetch id-ordered LIMIT batches, resuming after the last seen id.

    `.iterator()` would be simpler, but prod runs behind pgbouncer, which disables server-side
    cursors — Django then fetches the entire result set in one query. Keyset batches keep memory
    and per-query time bounded in every environment.
    """
    last_pk = None
    while True:
        batch_queryset = queryset.order_by("pk")
        if last_pk is not None:
            batch_queryset = batch_queryset.filter(pk__gt=last_pk)
        rows = list(batch_queryset[:batch_size])
        yield from rows
        if len(rows) < batch_size:
            return
        last_pk = rows[-1].pk


def scan_for_masked_secrets(
    *,
    team_ids: Sequence[int] | None = None,
    include_deleted: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_results: int | None = DEFAULT_MAX_RESULTS,
    max_scanned: int | None = None,
) -> MaskedSecretScan:
    queryset = (
        HogFunction.objects.select_related("team", "team__organization")
        .filter(Q(encrypted_inputs__isnull=False) | Q(draft_encrypted_inputs__isnull=False))
        # The rows carry hog source, bytecode, and filters the scan never reads. Defer them so a
        # fleet-wide sweep doesn't drag them over the wire.
        .only(
            "id",
            "name",
            "type",
            "template_id",
            "enabled",
            "deleted",
            "updated_at",
            "encrypted_inputs",
            "draft_encrypted_inputs",
            "team__id",
            "team__name",
            "team__organization__id",
            "team__organization__name",
        )
    )
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)

    findings: list[MaskedSecretFinding] = []
    scanned_count = 0
    truncated = False

    for hog_function in _keyset_batches(queryset, batch_size):
        if max_scanned is not None and scanned_count >= max_scanned:
            truncated = True
            break
        scanned_count += 1
        masked_live_inputs = _masked_input_keys(hog_function.encrypted_inputs)
        masked_draft_inputs = _masked_input_keys(hog_function.draft_encrypted_inputs)
        if not masked_live_inputs and not masked_draft_inputs:
            continue

        if max_results is not None and len(findings) >= max_results:
            truncated = True
            break

        team = hog_function.team
        findings.append(
            MaskedSecretFinding(
                organization_id=team.organization_id,
                organization_name=team.organization.name,
                team_id=team.id,
                team_name=team.name,
                hog_function_id=hog_function.id,
                hog_function_name=hog_function.name or "",
                hog_function_type=hog_function.type or "",
                template_id=hog_function.template_id or "",
                enabled=hog_function.enabled,
                deleted=hog_function.deleted,
                updated_at=hog_function.updated_at,
                masked_live_inputs=masked_live_inputs,
                masked_draft_inputs=masked_draft_inputs,
                # Not `hog_function.url`: that hardcodes the destinations route, which is the
                # wrong page for transformations, site apps, and source webhooks.
                configuration_url=absolute_uri(f"/project/{team.id}/functions/{hog_function.id}"),
            )
        )

    return MaskedSecretScan(findings=tuple(findings), scanned_count=scanned_count, truncated=truncated)


def scan_hog_flows_for_masked_secrets(
    *,
    team_ids: Sequence[int] | None = None,
    include_archived: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_results: int | None = DEFAULT_MAX_RESULTS,
    max_scanned: int | None = None,
) -> HogFlowMaskedSecretScan:
    queryset = (
        HogFlow.objects.select_related("team", "team__organization")
        .filter(Q(encrypted_inputs__isnull=False) | Q(draft_encrypted_inputs__isnull=False))
        # The rows carry the full action graph the scan never reads. Defer it so a fleet-wide
        # sweep doesn't drag it over the wire.
        .only(
            "id",
            "name",
            "status",
            "updated_at",
            "encrypted_inputs",
            "draft_encrypted_inputs",
            "team__id",
            "team__name",
            "team__organization__id",
            "team__organization__name",
        )
    )
    if not include_archived:
        queryset = queryset.exclude(status=HogFlow.State.ARCHIVED)
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)

    findings: list[HogFlowMaskedSecretFinding] = []
    scanned_count = 0
    truncated = False

    for hog_flow in _keyset_batches(queryset, batch_size):
        if max_scanned is not None and scanned_count >= max_scanned:
            truncated = True
            break
        scanned_count += 1
        masked_live_inputs = _flow_masked_input_keys(hog_flow.encrypted_inputs)
        masked_draft_inputs = _flow_masked_input_keys(hog_flow.draft_encrypted_inputs)
        if not masked_live_inputs and not masked_draft_inputs:
            continue

        if max_results is not None and len(findings) >= max_results:
            truncated = True
            break

        team = hog_flow.team
        findings.append(
            HogFlowMaskedSecretFinding(
                organization_id=team.organization_id,
                organization_name=team.organization.name,
                team_id=team.id,
                team_name=team.name,
                hog_flow_id=hog_flow.id,
                hog_flow_name=hog_flow.name or "",
                status=hog_flow.status,
                enabled=hog_flow.status == HogFlow.State.ACTIVE,
                updated_at=hog_flow.updated_at,
                masked_live_inputs=masked_live_inputs,
                masked_draft_inputs=masked_draft_inputs,
                configuration_url=absolute_uri(f"/project/{team.id}/workflows/{hog_flow.id}/workflow"),
            )
        )

    return HogFlowMaskedSecretScan(findings=tuple(findings), scanned_count=scanned_count, truncated=truncated)


def summarize_by_organization(
    findings: Iterable[MaskedSecretFinding | HogFlowMaskedSecretFinding],
) -> list[AffectedOrganization]:
    grouped: dict[UUID, list[MaskedSecretFinding | HogFlowMaskedSecretFinding]] = {}
    for finding in findings:
        grouped.setdefault(finding.organization_id, []).append(finding)

    summaries = [
        AffectedOrganization(
            organization_id=organization_id,
            organization_name=organization_findings[0].organization_name,
            team_ids=tuple(sorted({finding.team_id for finding in organization_findings})),
            finding_count=len(organization_findings),
            enabled_count=sum(1 for finding in organization_findings if finding.enabled),
        )
        for organization_id, organization_findings in grouped.items()
    ]
    # Enabled destinations and active workflows are the ones actively failing against the third
    # party, so the organizations to contact first sort to the top.
    summaries.sort(key=lambda summary: (-summary.enabled_count, -summary.finding_count))
    return summaries
