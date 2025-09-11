import json

from django.db import models

from posthog.models.utils import RootTeamMixin


class ScheduledChange(RootTeamMixin, models.Model):
    class AllowedModels(models.TextChoices):
        FEATURE_FLAG = "FeatureFlag", "feature flag"

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    record_id = models.CharField(max_length=200)
    model_name = models.CharField(max_length=100, choices=AllowedModels.choices)
    payload = models.JSONField(default=dict)
    scheduled_at = models.DateTimeField()
    executed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=400, null=True, blank=True)
    failure_count = models.IntegerField(default=0)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["scheduled_at", "executed_at"]),
        ]

    @property
    def formatted_failure_reason(self) -> str:
        """
        Return a user-friendly, safe failure message that excludes sensitive information.
        """
        if not self.failure_reason:
            return "Unknown error"

        # Try to parse as JSON (new format)
        try:
            failure_context = json.loads(self.failure_reason)

            if isinstance(failure_context, dict) and "error" in failure_context:
                error = failure_context.get("error", "Unknown error")
                will_retry = failure_context.get("will_retry")
                retry_exhausted = failure_context.get("retry_exhausted", False)
                error_classification = failure_context.get("error_classification")
                retry_count = failure_context.get("retry_count", 0)
                max_retries = failure_context.get("max_retries")

                # Only include the basic error message, not sensitive context
                message = str(error)

                # Add retry status info if available
                if will_retry is False and retry_exhausted:
                    if max_retries is not None:
                        message += f" (failed after {retry_count} out of {max_retries} attempts)"
                    else:
                        message += f" (failed after {retry_count} attempts)"
                elif will_retry is False and error_classification == "unrecoverable":
                    message += " (permanent error)"
                elif will_retry:
                    if max_retries is not None:
                        remaining_retries = max_retries - retry_count
                        attempt_word = "attempt" if remaining_retries == 1 else "attempts"
                        message += f" (will retry automatically, {remaining_retries} {attempt_word} remaining)"
                    else:
                        message += " (will retry automatically)"

                return message
        except (json.JSONDecodeError, TypeError):
            # Not JSON or invalid format, treat as plain string
            pass

        # Legacy format - return as-is (assume it's already sanitized)
        return str(self.failure_reason)
