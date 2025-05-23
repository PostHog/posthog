from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AIFreeSustainedRateThrottle, AIPaidSustainedRateThrottle
from rest_framework.throttling import BaseThrottle
from typing import cast


def get_ai_throttles(user: User, organization: Organization) -> list[BaseThrottle]:
    try:
        membership = OrganizationMembership.objects.get(user=cast(User, user), organization=organization)
        paid_user = any(
            product in membership.enabled_seat_based_products
            for product in [OrganizationMembership.SeatBasedProduct.MAX_AI]
            if membership.enabled_seat_based_products
        )
    except OrganizationMembership.DoesNotExist:
        paid_user = False
    return (
        [AIBurstRateThrottle(), AIPaidSustainedRateThrottle()]
        if paid_user
        else [AIBurstRateThrottle(), AIFreeSustainedRateThrottle()]
    )
