from typing import Optional

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

from rest_framework import exceptions, status

from posthog.constants import AvailableFeature
from posthog.models.utils import sane_repr
from posthog.tasks.tasks import sync_all_organization_available_product_features


class LicenseError(exceptions.APIException):
    """
    Exception raised for licensing errors.
    """

    default_type = "license_error"
    default_code = "license_error"
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "There was a problem with your current license."

    def __init__(self, code, detail):
        self.code = code
        self.detail = exceptions._get_error_details(detail, code)


class LicenseManager(models.Manager):
    def first_valid(self) -> Optional["License"]:
        """Return the highest valid license or cloud licenses if any"""
        valid_licenses = list(self.filter(Q(valid_until__gte=timezone.now()) | Q(plan="cloud")))
        if not valid_licenses:
            return None
        return max(
            valid_licenses,
            key=lambda license: License.PLAN_TO_SORTING_VALUE.get(license.plan, 0),
        )


class License(models.Model):
    objects: LicenseManager = LicenseManager()

    created_at = models.DateTimeField(auto_now_add=True)
    plan = models.CharField(max_length=200)
    valid_until = models.DateTimeField()
    key = models.CharField(max_length=200)
    # DEPRECATED: This is no longer used
    max_users = models.IntegerField(default=None, null=True)  # None = no restriction

    # NOTE: Remember to update the Billing Service as well. Long-term it will be the source of truth.
    SCALE_PLAN = "scale"
    SCALE_FEATURES = [
        AvailableFeature.ZAPIER,
        AvailableFeature.ORGANIZATIONS_PROJECTS,
        AvailableFeature.ENVIRONMENTS,
        AvailableFeature.SOCIAL_SSO,
        AvailableFeature.INGESTION_TAXONOMY,
        AvailableFeature.PATHS_ADVANCED,
        AvailableFeature.CORRELATION_ANALYSIS,
        AvailableFeature.GROUP_ANALYTICS,
        AvailableFeature.TAGGING,
        AvailableFeature.BEHAVIORAL_COHORT_FILTERING,
        AvailableFeature.WHITE_LABELLING,
        AvailableFeature.SUBSCRIPTIONS,
        AvailableFeature.APP_METRICS,
        AvailableFeature.RECORDINGS_PLAYLISTS,
        AvailableFeature.RECORDINGS_FILE_EXPORT,
        AvailableFeature.RECORDINGS_PERFORMANCE,
    ]

    ENTERPRISE_PLAN = "enterprise"
    ENTERPRISE_FEATURES = [
        *SCALE_FEATURES,
        AvailableFeature.ADVANCED_PERMISSIONS,
        AvailableFeature.SAML,
        AvailableFeature.SSO_ENFORCEMENT,
        AvailableFeature.ROLE_BASED_ACCESS,
    ]
    PLANS = {SCALE_PLAN: SCALE_FEATURES, ENTERPRISE_PLAN: ENTERPRISE_FEATURES}
    # The higher the plan, the higher its sorting value - sync with front-end licenseLogic
    PLAN_TO_SORTING_VALUE = {SCALE_PLAN: 10, ENTERPRISE_PLAN: 20}

    @property
    def available_features(self) -> list[AvailableFeature]:
        return self.PLANS.get(self.plan, [])

    @property
    def is_v2_license(self) -> bool:
        return self.key and len(self.key.split("::")) == 2

    __repr__ = sane_repr("key", "plan", "valid_until")


def get_licensed_users_available() -> Optional[int]:
    """
    Returns the number of user slots available that can be created based on the instance's current license.
    Not relevant for cloud users.
    `None` means unlimited users.
    """

    license = License.objects.first_valid()
    from posthog.models import OrganizationInvite

    if license:
        if license.max_users is None:
            return None

        users_left = license.max_users - get_user_model().objects.count() - OrganizationInvite.objects.count()
        return max(users_left, 0)

    return None


@receiver(post_save, sender=License)
def license_saved(sender, instance, created, raw, using, **kwargs):
    sync_all_organization_available_product_features()
