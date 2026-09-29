from uuid import UUID

import posthoganalytics

from posthog.models.person_group_membership.sql import PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG


def is_customer_analytics_active(organization_id: UUID | str) -> bool:
    organization_id = str(organization_id)
    return bool(
        posthoganalytics.feature_enabled(
            CUSTOMER_ANALYTICS_CSP_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def is_person_group_membership_eligible(organization_id: UUID | str, account_group_type_index: int | None) -> bool:
    return (
        account_group_type_index is not None
        and 0 <= account_group_type_index <= PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX
        and is_customer_analytics_active(organization_id)
    )
