from typing import Literal

from prometheus_client import Counter

# analytics_event: pr_created | pr_merged | pr_closed | pr_reviewed (bounded, code-defined).
# reason: unresolved_installation (no Integration matched the delivery's installation id) or
#         capture_exception (posthoganalytics.capture raised). Both paths were silent before,
#         so a webhook-side event loss only showed up as a capture-rate dip in analytics.
GITHUB_WEBHOOK_PR_EVENT_DROPPED_TOTAL = Counter(
    "posthog_tasks_github_webhook_pr_event_dropped_total",
    "GitHub PR webhook events that never reached PostHog capture, labeled by event and drop reason",
    labelnames=["analytics_event", "reason"],
)

# outcome: resolved | unresolved | timeout | error. timeout means the bounded org-member
# lookup hit statement_timeout and was skipped so the delivery survives without attribution.
GITHUB_WEBHOOK_ATTRIBUTION_TOTAL = Counter(
    "posthog_tasks_github_webhook_attribution_total",
    "Outcome of the org-member lookup that attributes a GitHub login on the pr_merged/pr_reviewed webhook path",
    labelnames=["outcome"],
)

GitHubWebhookAnalyticsEvent = Literal["pr_created", "pr_merged", "pr_closed", "pr_reviewed"]
GitHubWebhookDropReason = Literal["unresolved_installation", "capture_exception"]
GitHubWebhookAttributionOutcome = Literal["resolved", "unresolved", "timeout", "error"]


def observe_github_webhook_pr_event_dropped(
    *, analytics_event: GitHubWebhookAnalyticsEvent, reason: GitHubWebhookDropReason
) -> None:
    GITHUB_WEBHOOK_PR_EVENT_DROPPED_TOTAL.labels(analytics_event=analytics_event, reason=reason).inc()


def observe_github_webhook_attribution(*, outcome: GitHubWebhookAttributionOutcome) -> None:
    GITHUB_WEBHOOK_ATTRIBUTION_TOTAL.labels(outcome=outcome).inc()
