from datetime import datetime
from typing import Any

from django.apps import apps

from posthog.models import User

from products.customer_analytics.backend.models import (
    Account,
    AccountChannelSummary,
    AccountRelationship,
    AccountRelationshipDefinition,
    CustomPropertyDefinition,
    CustomPropertyValue,
    DisplayType,
    FeatureRequest,
    FeatureRequestAccountLink,
    FeatureRequestEvidence,
    FeatureRequestHistory,
    FeatureRequestProductArea,
    FeatureRequestProductAreaLink,
    Meeting,
)


def create_account(*, team_id: int, name: str = "Acme Corp", **kwargs: Any) -> Account:
    """Create an Account for tests. Always supplies `team_id` to make team-isolation cases ergonomic."""
    return Account.objects.unscoped().create(team_id=team_id, name=name, **kwargs)


def create_custom_property_value(
    *, team_id: int, account: Account, definition: CustomPropertyDefinition, **kwargs: Any
) -> CustomPropertyValue:
    return CustomPropertyValue.objects.for_team(team_id).create(
        team_id=team_id, account=account, definition=definition, **kwargs
    )


def create_account_relationship_definition(
    *, team_id: int, name: str = "CSM", **kwargs: Any
) -> AccountRelationshipDefinition:
    return AccountRelationshipDefinition.objects.for_team(team_id).create(team_id=team_id, name=name, **kwargs)


def create_account_relationship(
    *,
    team_id: int,
    account: Account,
    definition: AccountRelationshipDefinition,
    user: User | None = None,
    **kwargs: Any,
) -> AccountRelationship:
    return AccountRelationship.objects.for_team(team_id).create(
        team_id=team_id, account=account, definition=definition, user=user, **kwargs
    )


def create_feature_request(*, team_id: int, title: str = "Export reports", **kwargs: Any) -> FeatureRequest:
    return FeatureRequest.objects.for_team(team_id).create(team_id=team_id, title=title, **kwargs)


def create_feature_request_account_link(
    *, team_id: int, feature_request: FeatureRequest, account: Account, **kwargs: Any
) -> FeatureRequestAccountLink:
    return FeatureRequestAccountLink.objects.for_team(team_id).create(
        team_id=team_id, feature_request=feature_request, account=account, **kwargs
    )


def create_feature_request_product_area(
    *, team_id: int, name: str = "Reporting", **kwargs: Any
) -> FeatureRequestProductArea:
    return FeatureRequestProductArea.objects.for_team(team_id).create(team_id=team_id, name=name, **kwargs)


def create_feature_request_product_area_link(
    *, team_id: int, feature_request: FeatureRequest, product_area: FeatureRequestProductArea, **kwargs: Any
) -> FeatureRequestProductAreaLink:
    return FeatureRequestProductAreaLink.objects.for_team(team_id).create(
        team_id=team_id, feature_request=feature_request, product_area=product_area, **kwargs
    )


def create_feature_request_evidence(
    *, team_id: int, account_link: FeatureRequestAccountLink, source: str = "conversation", **kwargs: Any
) -> FeatureRequestEvidence:
    return FeatureRequestEvidence.objects.for_team(team_id).create(
        team_id=team_id, account_link=account_link, source=source, **kwargs
    )


def create_feature_request_history(
    *, team_id: int, feature_request: FeatureRequest, changed_at: datetime, changes: list | None = None, **kwargs: Any
) -> FeatureRequestHistory:
    return FeatureRequestHistory.objects.for_team(team_id).create(
        team_id=team_id, feature_request=feature_request, changed_at=changed_at, changes=changes or [], **kwargs
    )


def create_meeting(*, team_id: int, account: Account, ical_uid: str, start_time: datetime, **kwargs: Any) -> Meeting:
    return Meeting.objects.for_team(team_id).create(
        team_id=team_id, account=account, ical_uid=ical_uid, start_time=start_time, **kwargs
    )


def create_account_channel_summary(
    *,
    team_id: int,
    account: Account,
    slack_channel_id: str,
    cadence: str,
    period_start: datetime,
    period_end: datetime,
    content: str,
    **kwargs: Any,
) -> AccountChannelSummary:
    return AccountChannelSummary.objects.for_team(team_id).create(
        team_id=team_id,
        account=account,
        slack_channel_id=slack_channel_id,
        cadence=cadence,
        period_start=period_start,
        period_end=period_end,
        content=content,
        **kwargs,
    )


def create_custom_property_definition(
    *, team_id: int, name: str = "Plan", display_type: str = DisplayType.TEXT, **kwargs: Any
) -> CustomPropertyDefinition:
    """Create a CustomPropertyDefinition for tests, always supplying `team_id`."""
    return CustomPropertyDefinition.objects.unscoped().create(
        team_id=team_id, name=name, display_type=display_type, **kwargs
    )


def create_saved_query(
    *, team_id: int, name: str = "enriched_users", is_materialized: bool = True, **kwargs: Any
) -> Any:
    """Create a data-warehouse view for tests. Materialized by default, which is what a view-backed
    property source binds to.

    Resolved with ``apps.get_model`` because customer_analytics does not depend on data_modeling; the
    production code reaches the same model the same way.
    """
    saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
    return saved_query_model.objects.create(
        team_id=team_id, name=name, query={"query": "select 1"}, is_materialized=is_materialized, **kwargs
    )
