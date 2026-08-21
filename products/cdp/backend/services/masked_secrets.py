"""Find hog functions whose stored secret is the read-back mask instead of a real credential.

The UI shows a saved secret as `MASKED_SECRET_VALUE` and sends that mask back on a re-save to
mean "keep the stored value". When the two sides of that contract disagree, the mask is what
gets encrypted, the destination starts failing auth against the third party, and the real
credential is gone. Only the owner can restore it, so operators need the list of who to tell.

The match cannot be a SQL predicate. `encrypted_inputs` is Fernet-encrypted, and Fernet embeds a
timestamp and a random IV, so the same plaintext produces different ciphertext on every write.
Every candidate row has to be decrypted in Python and inspected.
"""

import csv
from collections.abc import Iterable, Sequence
from datetime import datetime
from io import StringIO
from uuid import UUID

from django.db.models import Q

from posthog.cdp.validation import MASKED_SECRET_VALUE
from posthog.dataclasses import frozen

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

DEFAULT_BATCH_SIZE = 500

# Bounds a fleet-wide sweep so an admin request cannot run unbounded. Callers are told when it
# bites rather than being handed a silently short list.
DEFAULT_MAX_RESULTS = 1000

CSV_COLUMNS = (
    "organization_id",
    "organization_name",
    "team_id",
    "team_name",
    "hog_function_id",
    "hog_function_name",
    "hog_function_type",
    "template_id",
    "enabled",
    "deleted",
    "updated_at",
    "masked_live_inputs",
    "masked_draft_inputs",
    "configuration_url",
)


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

    def as_csv_row(self) -> list[str]:
        return [
            str(self.organization_id),
            self.organization_name,
            str(self.team_id),
            self.team_name,
            str(self.hog_function_id),
            self.hog_function_name,
            self.hog_function_type,
            self.template_id,
            str(self.enabled),
            str(self.deleted),
            self.updated_at.isoformat(),
            " ".join(self.masked_live_inputs),
            " ".join(self.masked_draft_inputs),
            self.configuration_url,
        ]


@frozen
class AffectedOrganization:
    organization_id: UUID
    organization_name: str
    team_ids: tuple[int, ...]
    hog_function_count: int
    enabled_hog_function_count: int


@frozen
class MaskedSecretScan:
    findings: tuple[MaskedSecretFinding, ...]
    scanned_count: int
    # True when max_results stopped the sweep before the queryset was exhausted, so there are
    # more affected hog functions than `findings` shows.
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


def scan_for_masked_secrets(
    *,
    team_ids: Sequence[int] | None = None,
    include_deleted: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_results: int | None = DEFAULT_MAX_RESULTS,
) -> MaskedSecretScan:
    queryset = (
        HogFunction.objects.select_related("team", "team__organization")
        .filter(Q(encrypted_inputs__isnull=False) | Q(draft_encrypted_inputs__isnull=False))
        .order_by("team_id", "created_at")
    )
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)

    findings: list[MaskedSecretFinding] = []
    scanned_count = 0
    truncated = False

    for hog_function in queryset.iterator(chunk_size=batch_size):
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
                configuration_url=f"{hog_function.url}/configuration",
            )
        )

    return MaskedSecretScan(findings=tuple(findings), scanned_count=scanned_count, truncated=truncated)


def summarize_by_organization(findings: Iterable[MaskedSecretFinding]) -> list[AffectedOrganization]:
    grouped: dict[UUID, list[MaskedSecretFinding]] = {}
    for finding in findings:
        grouped.setdefault(finding.organization_id, []).append(finding)

    summaries = [
        AffectedOrganization(
            organization_id=organization_id,
            organization_name=organization_findings[0].organization_name,
            team_ids=tuple(sorted({finding.team_id for finding in organization_findings})),
            hog_function_count=len(organization_findings),
            enabled_hog_function_count=sum(1 for finding in organization_findings if finding.enabled),
        )
        for organization_id, organization_findings in grouped.items()
    ]
    # Enabled destinations are the ones actively failing against the third party, so the
    # organizations to contact first sort to the top.
    summaries.sort(key=lambda summary: (-summary.enabled_hog_function_count, -summary.hog_function_count))
    return summaries


def findings_as_csv(findings: Iterable[MaskedSecretFinding]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for finding in findings:
        writer.writerow(finding.as_csv_row())
    return buffer.getvalue()
