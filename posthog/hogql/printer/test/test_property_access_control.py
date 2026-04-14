from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import PropertyDefinition

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel


class TestRestrictPropertiesInHogQL(BaseTest):
    """Integration tests for property-level access control in HogQL query compilation."""

    def setUp(self):
        super().setUp()
        self.event_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_field",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        self.unrestricted_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="public_field",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )

    def _compile_select_with_values(self, query: str, user=None) -> tuple[str, dict]:
        if user is None:
            user = self.user
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=user,
            enable_select_queries=True,
        )
        node = parse_select(query)
        sql, _ = prepare_and_print_ast(node, context=context, dialect="clickhouse")
        return sql, context.values

    def _compile_select(self, query: str, user=None) -> str:
        sql, _ = self._compile_select_with_values(query, user)
        return sql

    def test_no_restrictions_passes_through(self):
        sql = self._compile_select("SELECT properties.secret_field FROM events")
        assert "secret_field" in sql

    def test_read_level_passes_through(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.READ.value,
        )
        sql = self._compile_select("SELECT properties.secret_field FROM events")
        assert "secret_field" in sql

    def test_denied_event_property_is_stripped_silently(self):
        # Restricted properties are removed from the JSON blob via JSONDropKeys rather than
        # raising an error, so explicit access (``properties.secret_field``) compiles to a
        # JSON extract over the stripped blob and resolves to an empty string at runtime.
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values("SELECT properties.secret_field FROM events")
        assert "JSONDropKeys" in sql
        # the restricted key only appears as a parameter placeholder — never as an inline literal
        assert "'secret_field'" not in sql
        assert "secret_field" in values.values()

    def test_allowed_property_not_affected(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql = self._compile_select("SELECT properties.public_field FROM events")
        assert "public_field" in sql

    def test_mixed_denied_and_allowed_strips_only_denied(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values(
            "SELECT properties.secret_field, properties.public_field FROM events"
        )
        assert "JSONDropKeys" in sql
        # the denied property is parameterised by JSONDropKeys, never inlined as a literal;
        # the allowed property is extracted by name (also parameterised)
        assert "'secret_field'" not in sql
        assert "secret_field" in values.values()
        assert "public_field" in values.values()

    def test_user_override_allows_access(self):
        # default: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # user-specific: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            organization_member=self.organization_membership,
        )
        sql = self._compile_select("SELECT properties.secret_field FROM events")
        assert "secret_field" in sql

    def test_denied_person_property_is_stripped_silently(self):
        # Restricted person properties are removed from ``person.properties`` rather than
        # raising — so the same query produces consistent (empty) output across PoE modes.
        person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_person_field",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values("SELECT person.properties.secret_person_field FROM events")
        assert "JSONDropKeys" in sql
        assert "'secret_person_field'" not in sql
        assert "secret_person_field" in values.values()

    def test_no_user_context_uses_default_rules(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=None,
            enable_select_queries=True,
        )
        node = parse_select("SELECT properties.secret_field FROM events")
        sql, _ = prepare_and_print_ast(node, context=context, dialect="clickhouse")
        # default rules still apply without a user — the restricted key is stripped
        assert "JSONDropKeys" in sql
        assert "'secret_field'" not in sql
        assert "secret_field" in context.values.values()

    def test_non_property_fields_not_affected(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql = self._compile_select("SELECT event, timestamp FROM events")
        assert "event" in sql
        assert "timestamp" in sql

    def test_denied_property_in_where_is_stripped(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # the WHERE clause compiles, but the restricted property is stripped from the JSON,
        # so the comparison effectively runs against an empty string
        sql, values = self._compile_select_with_values("SELECT event FROM events WHERE properties.secret_field = 'foo'")
        assert "JSONDropKeys" in sql
        assert "'secret_field'" not in sql
        assert "secret_field" in values.values()

    def test_select_star_works_with_restrictions(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # SELECT * should work because it expands to top-level columns,
        # not individual properties
        sql = self._compile_select("SELECT * FROM events")
        assert "event" in sql

    def test_role_override_allows_access(self):
        from ee.models.rbac.role import Role, RoleMembership

        role = Role.objects.create(name="Analyst", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)

        # default: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # role: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            role=role,
        )
        sql = self._compile_select("SELECT properties.secret_field FROM events")
        assert "secret_field" in sql

    def test_silent_strip_does_not_leak_access_control_information(self):
        # The compiled SQL must not embed the restricted property name as a literal,
        # error message, or comment — anything an attacker could read off the wire to
        # tell "this property exists but I can't see it" apart from "this property
        # doesn't exist". Restricted keys are passed through ``add_sensitive_value`` so
        # they appear only in the parameter dict, not the SQL string.
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values("SELECT properties.secret_field FROM events")
        # restricted key never appears as an inline literal in SQL — only as a parameter
        assert "'secret_field'" not in sql
        for forbidden_word in ["restricted", "denied", "permission", "not allowed"]:
            assert forbidden_word not in sql.lower(), f"SQL leaks access control info: '{sql}'"
        assert "secret_field" in values.values()

    @parameterized.expand(
        [
            ("events_properties", "SELECT properties FROM events", PropertyDefinition.Type.EVENT, "secret_field"),
            ("events_star", "SELECT * FROM events", PropertyDefinition.Type.EVENT, "secret_field"),
            (
                "events_person_properties",
                "SELECT person.properties FROM events",
                PropertyDefinition.Type.PERSON,
                "secret_person_field",
            ),
        ]
    )
    def test_restricted_properties_blob_uses_json_drop_keys(
        self,
        _case_name: str,
        query: str,
        property_type: int,
        restricted_key: str,
    ):
        property_definition = self.event_prop
        if property_type == PropertyDefinition.Type.PERSON:
            property_definition = PropertyDefinition.objects.create(
                team=self.team,
                name=restricted_key,
                property_type="String",
                type=PropertyDefinition.Type.PERSON,
            )

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=property_definition,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values(query)
        assert "JSONDropKeys" in sql
        assert restricted_key not in sql
        assert restricted_key in values.values()

    def test_properties_blob_no_wrapping_without_restrictions(self):
        sql = self._compile_select("SELECT properties FROM events")
        assert "JSONDropKeys" not in sql

    def test_properties_blob_strips_multiple_restricted_keys(self):
        another_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="another_secret",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=another_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values("SELECT properties FROM events")
        assert "JSONDropKeys" in sql
        assert "another_secret" not in sql
        assert "secret_field" not in sql
        assert "another_secret" in values.values()
        assert "secret_field" in values.values()

    @parameterized.expand([("persons",), ("raw_persons",)])
    def test_persons_tables_properties_blob_strips_restricted_keys(self, table_name: str):
        person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_person_field",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values(f"SELECT properties FROM {table_name}")
        assert "JSONDropKeys" in sql
        assert "secret_person_field" not in sql
        assert "secret_person_field" in values.values()

    def test_event_restriction_does_not_affect_person_properties_blob(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # restricting an event property should not wrap person.properties in JSONDropKeys
        sql = self._compile_select("SELECT person.properties FROM events")
        assert "JSONDropKeys" not in sql

    def test_restrictions_do_not_affect_non_event_or_person_tables(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # the groups table has a StringJSONDatabaseField named "properties",
        # but restrictions should only apply to events/persons tables
        sql = self._compile_select("SELECT properties FROM groups")
        assert "JSONDropKeys" not in sql

    def test_explicit_property_access_on_non_event_table_not_blocked(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # accessing properties.secret_field on the groups table should not raise,
        # even though "secret_field" is restricted on the events table
        sql = self._compile_select("SELECT properties.secret_field FROM groups")
        assert "secret_field" in sql

    def test_column_aliased_properties_blob_still_uses_json_drop_keys(self):
        # regression: ColumnAliasedTableType (``FROM events AS e(uuid, event, properties_alias)``)
        # exposed ``properties`` under a different AST name; the guard previously compared the
        # alias to "properties" and skipped JSONDropKeys, leaking restricted keys.
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values("SELECT e.c FROM events AS e (a, b, c)")
        assert "JSONDropKeys" in sql
        assert "secret_field" not in sql
        assert "secret_field" in values.values()

    def test_column_aliased_explicit_property_access_is_stripped(self):
        # regression: explicit access ``e.c.secret_field`` (where ``c`` aliases ``properties``)
        # must be stripped via JSONDropKeys, matching the unaliased case.
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql, values = self._compile_select_with_values("SELECT e.c.secret_field FROM events AS e (a, b, c)")
        assert "JSONDropKeys" in sql
        assert "'secret_field'" not in sql
        assert "secret_field" in values.values()

    @parameterized.expand(
        [
            ("disabled_joined", PersonsOnEventsMode.DISABLED),
            ("poe_no_override", PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS),
            ("poe_override", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
            ("override_joined", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        ]
    )
    def test_person_property_access_is_consistent_across_poe_modes(
        self, _case_name: str, persons_on_events_mode: PersonsOnEventsMode
    ):
        # regression: previously, ``person.properties.email`` raised a ResolutionError in joined
        # mode but silently returned an empty value in PoE mode. The intended behaviour is to
        # strip restricted keys from the JSON blob (returning empty) in *all* modes, so the same
        # query produces the same compiled output regardless of how person properties are sourced.
        person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="email",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=self.user,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(personsOnEventsMode=persons_on_events_mode),
        )
        node = parse_select("SELECT uuid, event, person.properties.email FROM events")
        sql, _ = prepare_and_print_ast(node, context=context, dialect="clickhouse")
        assert "JSONDropKeys" in sql
        # the restricted key never leaks as an inline literal in any PoE mode
        assert "'email'" not in sql
        assert "email" in context.values.values()
