from typing import Any

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

WAREHOUSE_ACCESS_CONTROL_FLAG = "posthog.hogql.database.database._evaluate_warehouse_access_control_flag"


def filter_through_warehouse_join(team: Team) -> dict[str, Any]:
    """A person property filter that reads `denied_warehouse_table` through a join on persons."""
    credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=team)
    DataWarehouseTable.objects.create(
        name="denied_warehouse_table",
        format=DataWarehouseTable.TableFormat.Parquet,
        team=team,
        credential=credential,
        url_pattern="s3://bucket/denied/*",
        columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True}},
    )
    DataWarehouseJoin.objects.create(
        team=team,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name="denied_warehouse_table",
        joining_table_key="id",
        field_name="denied_join",
    )
    return {"type": "data_warehouse_person_property", "key": "denied_join.id", "value": "internal", "operator": "exact"}


def deny_warehouse_table_to_member(organization: Organization, team: Team, user: User) -> dict[str, Any]:
    """Make the user a plain member who is denied `denied_warehouse_table`, and return a filter
    that reads that table. Patch `WAREHOUSE_ACCESS_CONTROL_FLAG` to True for the denial to apply."""
    organization.available_product_features = [
        {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
    ]
    organization.save()
    membership = OrganizationMembership.objects.get(user=user, organization=organization)
    membership.level = OrganizationMembership.Level.MEMBER
    membership.save()

    denied_filter = filter_through_warehouse_join(team)
    AccessControl.objects.create(
        team=team,
        resource="warehouse_table",
        resource_id=str(DataWarehouseTable.objects.get(team=team, name="denied_warehouse_table").id),
        access_level="none",
        organization_member=membership,
    )
    return denied_filter
