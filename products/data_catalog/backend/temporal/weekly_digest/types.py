import dataclasses
from enum import StrEnum

from posthog.temporal.common.digest import DigestBatchTotals


class DigestOutcome(StrEnum):
    """Outcome of attempting to send a single digest email to a single user."""

    SENT = "sent"
    DRY_RUN = "dry_run"
    SKIPPED_OPTOUT = "skipped_optout"
    SKIPPED_NO_DATA = "skipped_no_data"
    FAILED = "failed"


@dataclasses.dataclass(frozen=False)
class OrgDigestCounts:
    """`skipped_reason` is set when the org was skipped before any email attempt
    (no teams, no targeted members, nothing to review), so the org counts as
    skipped rather than processed.
    """

    sent: int = 0
    skipped_optout: int = 0
    skipped_no_data: int = 0
    failed: int = 0
    team_count: int = 0
    teams_failed: int = 0
    build_duration: float = 0.0
    send_duration: float = 0.0
    skipped_reason: str | None = None


@dataclasses.dataclass(frozen=True)
class DataCatalogWeeklyDigestInput:
    # True so an input-less manual run, such as one started from the Temporal UI, cannot send real
    # mail. The registered schedule is the one caller that passes False.
    dry_run: bool = True
    batch_size: int = 25
    max_concurrent: int = 4
    failure_threshold: float = 0.2
    active_since_days: int | None = 30
    org_ids: list[str] | None = None

    # Pushgateway deletes every gauge already pushed under the job name, so a scoped or dry run
    # would replace the week's numbers and advance the last-run timestamp. Only a full real run
    # speaks for the week.
    @property
    def publishes_metrics(self) -> bool:
        return self.org_ids is None and not self.dry_run


@dataclasses.dataclass(frozen=True)
class OrgBatchPageInput:
    workflow_input: DataCatalogWeeklyDigestInput
    cursor: str | None = None
    page_size: int = 5000


@dataclasses.dataclass(frozen=True)
class DigestBatchInput:
    org_ids: list[str]
    dry_run: bool = False


@dataclasses.dataclass(frozen=False)
class DigestBatchResult(DigestBatchTotals):
    emails_sent: int = 0
    emails_skipped_optout: int = 0
    emails_skipped_no_data: int = 0
    emails_failed: int = 0


@dataclasses.dataclass(frozen=True)
class SendTestDigestInput:
    """Input for the test activity.

    Sends the user their real digest for every organization they belong to, bypassing the
    notification setting and the feature flag. Organization membership and project access are
    always enforced.
    """

    email: str


DATA_CATALOG_DIGEST_THRESHOLD_EXCEEDED_TYPE = "DataCatalogDigestThresholdExceeded"
DATA_CATALOG_DIGEST_EMAIL_UNAVAILABLE_TYPE = "DataCatalogDigestEmailUnavailable"
