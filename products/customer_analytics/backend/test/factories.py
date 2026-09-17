from collections.abc import Iterable
from datetime import datetime
from typing import Any

from django.utils import timezone

from posthog.models import User

from products.customer_analytics.backend.models import (
    Account,
    AccountChannelSummary,
    AccountRelationship,
    AccountRelationshipControl,
    AccountRelationshipDefinition,
    CustomerTask,
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
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


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


def enroll_account(
    account: Account, definition: AccountRelationshipDefinition, *, controlled_at: datetime | None = None
) -> AccountRelationshipControl:
    """A control row written directly, for tests that need a known fence rather than the audited
    enrollment path."""
    return AccountRelationshipControl.objects.for_team(account.team_id).create(
        team_id=account.team_id, account=account, definition=definition, controlled_at=controlled_at or timezone.now()
    )


def create_customer_task(*, team_id: int, name: str = "Review account", **kwargs: Any) -> CustomerTask:
    return CustomerTask.objects.for_team(team_id).create(team_id=team_id, name=name, **kwargs)


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
) -> DataWarehouseSavedQuery:
    """Create a data-warehouse view for tests. Materialized by default, which is what a view-backed
    property source binds to."""
    return DataWarehouseSavedQuery.objects.create(
        team_id=team_id, name=name, query={"query": "select 1"}, is_materialized=is_materialized, **kwargs
    )


def saved_query_columns(names: Iterable[str]) -> dict[str, dict[str, str]]:
    """Columns in the shape data_modeling stores after a run. Its facade drops a column with no
    ``clickhouse`` type, so a bare ``{}`` entry would read back as missing."""
    return {name: {"clickhouse": "String"} for name in names}
