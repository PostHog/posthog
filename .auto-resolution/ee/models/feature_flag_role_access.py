from django.db import models


# DEPRECATED - do not use
class FeatureFlagRoleAccess(models.Model):
    feature_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        on_delete=models.CASCADE,
        related_name="access",
        related_query_name="access",
    )
    role = models.ForeignKey(
        "Role",
        on_delete=models.CASCADE,
        related_name="feature_flag_access",
        related_query_name="feature_flag_access",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "feature_flag"], name="unique_feature_flag_and_role")]
