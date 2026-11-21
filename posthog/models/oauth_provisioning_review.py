"""The review a self-registered CIMD provisioning partner goes through before it can provision.

A CIMD client becomes a provisioning partner by publishing an opt-in in its own metadata
document, with no person at PostHog involved. The review stands in for that person: until it
accepts the client, the partner's provisioning stays inactive, and a rejection switches it off
through the ``disabled`` kill switch, which registering again cannot clear. Staff can reverse a
verdict, and every verdict lands in the run log. The pipeline itself lives in
``posthog/temporal/cimd_provisioning_review/``.
"""

from django.db import models

from posthog.models.utils import UUIDModel


class ProvisioningReviewStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    # The pipeline could not settle it. The partner stays inactive until staff decide.
    NEEDS_HUMAN = "needs_human", "Needs staff review"


class ProvisioningReviewStage(models.TextChoices):
    # Jev could not settle it, but another client on the same host was already accepted.
    HOST_ALREADY_ACCEPTED = "host_already_accepted", "Host already accepted"
    # Jev judged the client with its homepage and web search results.
    RESEARCH = "research", "Research"
    # The pipeline failed, so the review went to staff without a verdict.
    PIPELINE_FAILED = "pipeline_failed", "Pipeline failed"
    STAFF = "staff", "Staff"


class PartnerProvisioningStatus(models.TextChoices):
    """Whether an app can provision, as its owners see it. Follows the partner gates, which read
    `OAuthApplication.provisioning_allowed`."""

    NOT_A_PARTNER = "not_a_partner", "Not a provisioning partner"
    IN_REVIEW = "in_review", "In review"
    WAITING_FOR_STAFF = "waiting_for_staff", "Waiting for PostHog staff"
    ON = "on", "On"
    OFF = "off", "Off"
    BLOCKED = "blocked", "Blocked"


class CIMDProvisioningReview(UUIDModel):
    application = models.OneToOneField(
        "posthog.OAuthApplication", on_delete=models.CASCADE, related_name="provisioning_review"
    )
    # The registrable domain of the client_id, so a second client on an accepted domain can skip
    # the pipeline. Tenants of a shared host (a.github.io, b.github.io) are different domains.
    domain = models.CharField(max_length=253, db_index=True)
    status = models.CharField(
        max_length=16, choices=ProvisioningReviewStatus.choices, default=ProvisioningReviewStatus.PENDING
    )
    decided_stage = models.CharField(max_length=32, choices=ProvisioningReviewStage.choices, null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    # Written by staff for the partner's organization admins, who see it in PostHog. `reason` stays
    # internal, because it can name what the review checks.
    # db_default, so a server still on the previous release can insert a review during a deploy.
    partner_message = models.TextField(blank=True, default="", db_default="")
    # The client metadata document the partner registered with. The app row keeps only some of its
    # fields, and the rest (client_uri, policy links, contacts) is evidence for the review.
    metadata_document = models.JSONField(null=True, blank=True)
    research_evidence = models.JSONField(null=True, blank=True)
    research_judgment = models.JSONField(null=True, blank=True)
    # What each workflow step did, in order, for staff to read in the console without Temporal.
    run_log = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    # The staff Slack thread for this review: the message posted when it first settled, which every
    # later decision replies under. Empty until the first post.
    slack_channel_id = models.CharField(max_length=32, blank=True, default="", db_default="")
    slack_message_ts = models.CharField(max_length=32, blank=True, default="", db_default="")

    class Meta:
        indexes = [models.Index(fields=["status", "created_at"], name="cimd_prov_review_status_idx")]

    def __str__(self) -> str:
        return f"{self.domain} ({self.status})"
