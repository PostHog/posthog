from typing import Any

import pytest

from posthog.models import Organization, Team, User

from ee.hogai.ai.products.analytics import AnalyticsAIProduct
from ee.hogai.ai.products_infrastructure import get_all_tool_schemas
from ee.hogai.graph.root.nodes import RootNode
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.types import AssistantState


@pytest.fixture(autouse=True)
def enable_ai_products(settings):
    settings.TEST = True
    settings.AI_PRODUCTS_LOAD_IN_TEST = True


@pytest.mark.django_db
def test_ai_product_registry_exposes_expected_tool_schemas():
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@example.com", distinct_id="test")

    schemas = get_all_tool_schemas(team, user)
    schema_names = {Schema.__name__ for Schema in schemas}

    expected = {
        "create_and_query_insight",
        "fix_hogql_query",
        "search_session_recordings",
        "create_survey",
        "analyze_survey_responses",
        "create_message_template",
        "filter_error_tracking_issues",
        "find_error_tracking_impactful_issue_event_list",
    }

    assert expected.intersection(schema_names), f"No expected product tool schemas found. Got: {sorted(schema_names)}"


@pytest.mark.django_db
def test_rootnode_includes_product_tool_schemas_in_bind(monkeypatch):
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@example.com", distinct_id="test")

    captured: dict[str, Any] = {}

    def fake_bind_tools(self, tools, parallel_tool_calls=False):  # type: ignore[override]
        captured["tools"] = tools
        return "BOUND"

    monkeypatch.setattr(MaxChatAnthropic, "bind_tools", fake_bind_tools, raising=False)

    root = RootNode(team, user)
    state = AssistantState(messages=[])
    config = {"configurable": {"team": team, "user": user, "contextual_tools": {}}}

    bound = root._get_model(state, config)
    assert bound == "BOUND"

    tool_classes = captured["tools"]
    tool_names = {getattr(cls, "__name__", getattr(cls, "name", str(cls))) for cls in tool_classes}
    expected_any = {"create_and_query_insight", "fix_hogql_query", "search_session_recordings"}
    assert expected_any.intersection(
        tool_names
    ), f"No expected product tool schemas were passed to bind_tools. Got: {sorted(tool_names)}"


@pytest.mark.django_db
def test_rootnode_includes_contextual_tools_alongside_products(monkeypatch):
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@example.com", distinct_id="test")

    captured: dict[str, Any] = {}

    def fake_bind_tools(self, tools, parallel_tool_calls=False):  # type: ignore[override]
        captured["tools"] = tools
        return "BOUND"

    monkeypatch.setattr(MaxChatAnthropic, "bind_tools", fake_bind_tools, raising=False)

    root = RootNode(team, user)
    state = AssistantState(messages=[])
    config = {
        "configurable": {
            "team": team,
            "user": user,
            "contextual_tools": {"navigate": {"current_page": "insights"}},
        }
    }

    bound = root._get_model(state, config)
    assert bound == "BOUND"

    tools = captured.get("tools", [])
    names = set()
    has_navigate_instance = False
    for t in tools:
        if getattr(t, "name", None) == "navigate":
            has_navigate_instance = True
        names.add(getattr(t, "__name__", getattr(t, "name", str(t))))

    assert has_navigate_instance, "Contextual tool 'navigate' not included in bind_tools"
    assert any(
        n in names for n in {"fix_hogql_query", "create_and_query_insight", "search_session_recordings"}
    ), f"No product tool schemas found alongside contextual tools. Got: {sorted(names)}"


@pytest.mark.django_db
def test_product_gating_excludes_tools_in_registry(monkeypatch):
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@example.com", distinct_id="test")

    monkeypatch.setattr(
        AnalyticsAIProduct,
        "is_available",
        classmethod(lambda cls, team, user: False),
        raising=False,
    )

    schemas = get_all_tool_schemas(team, user)
    schema_names = {Schema.__name__ for Schema in schemas}
    assert "fix_hogql_query" not in schema_names


@pytest.mark.django_db
def test_product_gating_excludes_tools_in_root_bind(monkeypatch):
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@example.com", distinct_id="test")

    monkeypatch.setattr(
        AnalyticsAIProduct,
        "is_available",
        classmethod(lambda cls, team, user: False),
        raising=False,
    )

    captured: dict[str, Any] = {}

    def fake_bind_tools(self, tools, parallel_tool_calls=False):  # type: ignore[override]
        captured["tools"] = tools
        return "BOUND"

    monkeypatch.setattr(MaxChatAnthropic, "bind_tools", fake_bind_tools, raising=False)

    root = RootNode(team, user)
    state = AssistantState(messages=[])
    config = {"configurable": {"team": team, "user": user, "contextual_tools": {}}}
    bound = root._get_model(state, config)
    assert bound == "BOUND"

    tools = captured.get("tools", [])
    names = {getattr(t, "__name__", getattr(t, "name", str(t))) for t in tools}
    assert "fix_hogql_query" not in names
