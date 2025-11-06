import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.models import Dashboard, Insight, Organization, OrganizationMembership, Team, User

from products.dashboards.backend.max_tools import EditCurrentDashboardTool
from products.enterprise.backend.hogai.graph.dashboards.nodes import QueryMetadata
from products.enterprise.backend.hogai.utils.types.base import InsightQuery
from products.enterprise.backend.models.assistant import Conversation
from products.enterprise.backend.models.rbac.access_control import AccessControl


@sync_to_async
def _create_dashboard_setup(org_name, user_email, create_permissions=True):
    org = Organization.objects.create(name=org_name)
    # Enable ADVANCED_PERMISSIONS feature for the organization
    from posthog.constants import AvailableFeature

    org.available_product_features = [{"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced Permissions"}]
    org.save()
    team = Team.objects.create(organization=org)
    user = User.objects.create(organization=org, email=user_email)

    # Create organization membership first
    org_membership = OrganizationMembership.objects.create(
        organization=org, user=user, level=OrganizationMembership.Level.MEMBER
    )

    # Create a different user as the dashboard creator to test permissions properly
    creator = User.objects.create(organization=org, email=f"creator_{user_email}")
    _ = OrganizationMembership.objects.create(organization=org, user=creator, level=OrganizationMembership.Level.MEMBER)

    # Create dashboard with different user as creator
    dashboard = Dashboard.objects.create(
        name="Test Dashboard",
        team=team,
        created_by=creator,
        restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
    )
    conversation = Conversation.objects.create(team=team, user=user)

    access_control = None
    if create_permissions:
        # Create access control with organization_member instead of user
        access_control = AccessControl.objects.create(
            team=team,
            resource="dashboard",
            resource_id=str(dashboard.id),
            organization_member=org_membership,
            access_level="editor",
        )
        # Also create DashboardPrivilege for legacy system
        from products.enterprise.backend.models import DashboardPrivilege

        DashboardPrivilege.objects.create(user=user, dashboard=dashboard, level=Dashboard.PrivilegeLevel.CAN_EDIT)

    return dashboard, conversation, access_control


@sync_to_async
def _teardown_dashboard_setup(dashboard, conversation, access_control):
    creator = dashboard.created_by
    # Clean up creator
    OrganizationMembership.objects.filter(user=creator).delete()
    creator.delete()

    # Clean up conversation user
    user = conversation.user
    OrganizationMembership.objects.filter(user=user).delete()
    user.delete()

    dashboard.delete()
    conversation.delete()
    if access_control:
        access_control.delete()


@pytest.fixture
async def dashboard_setup():
    dashboard, conversation, access_control = await _create_dashboard_setup(
        "org", "teeest@test.com", create_permissions=True
    )

    yield dashboard, conversation, access_control

    await _teardown_dashboard_setup(dashboard, conversation, access_control)


@pytest.mark.django_db
async def test_dashboard_metadata_update(dashboard_setup):
    dashboard, conversation, _ = dashboard_setup
    tool = EditCurrentDashboardTool(
        team=dashboard.team,
        user=conversation.user,
        config=RunnableConfig(
            configurable={
                "thread_id": conversation.id,
                "team": dashboard.team,
                "user": conversation.user,
                "contextual_tools": {"edit_current_dashboard": {"current_dashboard": {"id": dashboard.id}}},
            }
        ),
    )
    result_message, _ = await tool._arun_impl(dashboard_name="New Dashboard", dashboard_description="New description")
    await dashboard.arefresh_from_db()
    assert dashboard.name == "New Dashboard"
    assert dashboard.description == "New description"
    assert (
        result_message
        == "Dashboard was renamed to New Dashboard successfully. Dashboard description was updated successfully. "
    )


@pytest.fixture
async def dashboard_setup_no_perms():
    dashboard, conversation, access_control = await _create_dashboard_setup(
        "org_no_perms", "no_permsdddd@test.com", create_permissions=False
    )

    yield dashboard, conversation, access_control

    await _teardown_dashboard_setup(dashboard, conversation, access_control)


@pytest.mark.django_db
async def test_dashboard_metadata_update_no_permissions(dashboard_setup_no_perms):
    dashboard, conversation, _ = dashboard_setup_no_perms
    tool = EditCurrentDashboardTool(
        team=dashboard.team,
        user=conversation.user,
        config=RunnableConfig(
            configurable={
                "thread_id": conversation.id,
                "team": dashboard.team,
                "user": conversation.user,
                "contextual_tools": {"edit_current_dashboard": {"current_dashboard": {"id": dashboard.id}}},
            }
        ),
    )
    result_message, _ = await tool._arun_impl(dashboard_name="New Dashboard")
    assert result_message == "The user does not have permission to edit this dashboard."
    await dashboard.arefresh_from_db()
    assert dashboard.name == "Test Dashboard"


@pytest.mark.django_db
async def test_dashboard_add_insights(dashboard_setup):
    dashboard, conversation, _ = dashboard_setup
    tool = EditCurrentDashboardTool(
        team=dashboard.team,
        user=conversation.user,
        config=RunnableConfig(
            configurable={
                "thread_id": conversation.id,
                "team": dashboard.team,
                "user": conversation.user,
                "contextual_tools": {"edit_current_dashboard": {"current_dashboard": {"id": dashboard.id}}},
            }
        ),
    )

    # Create insights to add
    insights_to_add = [
        InsightQuery(name="User Activity", description="Track user activity over time"),
    ]

    # Mock the DashboardCreationNode to simulate successful insight creation
    with patch("ee.hogai.graph.dashboards.nodes.DashboardCreationNode._search_insights") as mock_search_insights:
        # Create a mock insight
        mock_insight = await Insight.objects.acreate(
            name="User Activity",
            description="Track user activity over time",
            team=dashboard.team,
            created_by=conversation.user,
        )

        mock_search_insights.return_value = {
            "0": QueryMetadata(
                found_insight_ids={mock_insight.id},
                created_insight_ids=set(),
                found_insight_messages=["Found insights"],
                created_insight_messages=[],
                query=InsightQuery(name="User Activity", description="Track user activity over time"),
            )
        }

        result_message, _ = await tool._arun_impl(insights_to_add=insights_to_add)

        # The tool should have successfully added insights
        assert "successfully" in result_message.lower()

        # Verify the insights were added to the dashboard
        await dashboard.arefresh_from_db()
        insights = [insight async for insight in dashboard.insights.all()]
        assert len(insights) == 1
        assert insights[0].name == "User Activity"
        assert insights[0].description == "Track user activity over time"
