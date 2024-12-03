from django.test import TestCase
from posthog.cdp.site_functions import get_transpiled_function
from posthog.models.action.action import Action
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.plugin import TranspilerError
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.user import User


class TestSiteFunctions(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Organization")
        self.user = User.objects.create_user(email="testuser@example.com", first_name="Test", password="password")
        self.organization.members.add(self.user)
        self.project, self.team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )

    def test_get_transpiled_function_basic(self):
        id = "123"
        source = 'export function onLoad() { console.log("Hello, World!"); }'
        filters: dict = {}
        inputs: dict = {}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn('console.log("Hello, World!")', result)
        self.assertIn(f"window['__$$ph_site_app_{id}_posthog']", result)

    def test_get_transpiled_function_with_static_input(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.message); }"
        filters: dict = {}
        inputs = {"message": {"value": "Hello, Inputs!"}}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.message);", result)
        self.assertIn("inputs = {", result)
        self.assertIn('"message": "Hello, Inputs!"', result)

    def test_get_transpiled_function_with_template_input(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.greeting); }"
        filters: dict = {}
        inputs = {"greeting": {"value": "Hello, {person.properties.name}!"}}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.greeting);", result)
        # Check that the input processing code is included
        self.assertIn("function getInputsKey", result)
        self.assertIn('inputs["greeting"] = getInputsKey("greeting");', result)
        self.assertIn('case "greeting": return ', result)
        self.assertIn('__getGlobal("person")', result)

    def test_get_transpiled_function_with_filters(self):
        id = "123"
        source = "export function onEvent(event) { console.log(event.event); }"
        filters: dict = {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]}
        inputs: dict = {}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(event.event);", result)
        self.assertIn("const filterMatches = ", result)
        self.assertIn('__getGlobal("event") == "$pageview"', result)
        self.assertIn("if (filterMatches) { response.onEvent({", result)

    def test_get_transpiled_function_with_invalid_template_input(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.greeting); }"
        filters: dict = {}
        inputs = {"greeting": {"value": "Hello, {person.properties.nonexistent_property}!"}}
        team = self.team

        # This should not raise an exception during transpilation
        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.greeting);", result)

    def test_get_transpiled_function_with_syntax_error_in_source(self):
        id = "123"
        source = 'export function onLoad() { console.log("Missing closing brace");'
        filters: dict = {}
        inputs: dict = {}
        team = self.team

        with self.assertRaises(TranspilerError):
            get_transpiled_function(id, source, filters, inputs, team)

    def test_get_transpiled_function_with_complex_inputs(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.complexInput); }"
        filters: dict = {}
        inputs = {
            "complexInput": {
                "value": {
                    "nested": "{event.properties.url}",
                    "list": ["{person.properties.name}", "{groups.group_name}"],
                }
            }
        }
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.complexInput);", result)
        self.assertIn("function getInputsKey", result)
        self.assertIn('inputs["complexInput"] = getInputsKey("complexInput");', result)

    def test_get_transpiled_function_with_empty_inputs(self):
        id = "123"
        source = 'export function onLoad() { console.log("No inputs"); }'
        filters: dict = {}
        inputs: dict = {}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn('console.log("No inputs");', result)
        self.assertIn("let inputs = {\n};", result)

    def test_get_transpiled_function_with_non_template_string(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.staticMessage); }"
        filters: dict = {}
        inputs = {"staticMessage": {"value": "This is a static message."}}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.staticMessage);", result)
        # Since the value does not contain '{', it should be added directly to inputs object
        self.assertIn('"staticMessage": "This is a static message."', result)
        self.assertNotIn("function getInputsKey", result)

    def test_get_transpiled_function_with_list_inputs(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.messages); }"
        filters: dict = {}
        inputs = {"messages": {"value": ["Hello", "World", "{person.properties.name}"]}}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.messages);", result)
        self.assertIn("function getInputsKey", result)
        self.assertIn('inputs["messages"] = getInputsKey("messages");', result)

    def test_get_transpiled_function_with_event_filter(self):
        id = "123"
        source = "export function onEvent(event) { console.log(event.properties.url); }"
        filters: dict = {
            "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
            "filter_test_accounts": True,
        }
        inputs: dict = {}
        team = self.team
        # Assume that team.test_account_filters is set up
        team.test_account_filters = [{"key": "email", "value": "@test.com", "operator": "icontains", "type": "person"}]
        team.save()

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(event.properties.url);", result)
        self.assertIn("const filterMatches = ", result)
        self.assertIn('__getGlobal("event") == "$pageview"', result)
        self.assertIn(
            '(ilike(__getProperty(__getProperty(__getGlobal("person"), "properties", true), "email", true), "%@test.com%")',
            result,
        )

    def test_get_transpiled_function_with_groups(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.groupInfo); }"
        filters: dict = {}
        inputs = {"groupInfo": {"value": "{groups['company']}"}}
        team = self.team

        # Set up group type mapping
        GroupTypeMapping.objects.create(team=team, group_type="company", group_type_index=0, project=self.project)

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.groupInfo);", result)
        self.assertIn('inputs["groupInfo"] = getInputsKey("groupInfo");', result)
        self.assertIn('__getProperty(__getGlobal("groups"), "company", false)', result)

    def test_get_transpiled_function_with_missing_group(self):
        id = "123"
        source = "export function onLoad() { console.log(inputs.groupInfo); }"
        filters: dict = {}
        inputs = {"groupInfo": {"value": "{groups['nonexistent']}"}}
        team = self.team

        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(inputs.groupInfo);", result)
        self.assertIn('inputs["groupInfo"] = getInputsKey("groupInfo");', result)
        self.assertIn('__getProperty(__getGlobal("groups"), "nonexistent"', result)

    def test_get_transpiled_function_with_complex_filters(self):
        action = Action.objects.create(team=self.team, name="Test Action")
        action.steps = [{"event": "$pageview", "url": "https://example.com"}]  # type: ignore
        action.save()
        id = "123"
        source = "export function onEvent(event) { console.log(event.event); }"
        filters: dict = {
            "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
            "actions": [{"id": str(action.pk), "name": "Test Action", "type": "actions"}],
            "filter_test_accounts": True,
        }
        inputs: dict = {}
        team = self.team
        result = get_transpiled_function(id, source, filters, inputs, team)

        self.assertIsInstance(result, str)
        self.assertIn("console.log(event.event);", result)
        self.assertIn("const filterMatches = ", result)
        self.assertIn('__getGlobal("event") == "$pageview"', result)
        self.assertIn("https://example.com", result)
