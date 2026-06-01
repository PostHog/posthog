from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ResolutionError
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

    def _compile_select(self, query: str, user=None) -> str:
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

    def test_denied_event_property_raises_error(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        with self.assertRaises(ResolutionError) as cm:
            self._compile_select("SELECT properties.secret_field FROM events")
        assert "secret_field" in str(cm.exception)
        assert "properties" in str(cm.exception)

    def test_allowed_property_not_affected(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql = self._compile_select("SELECT properties.public_field FROM events")
        assert "public_field" in sql

    def test_mixed_denied_and_allowed_raises_for_denied(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        with self.assertRaises(ResolutionError) as cm:
            self._compile_select("SELECT properties.secret_field, properties.public_field FROM events")
        assert "secret_field" in str(cm.exception)

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

    def test_denied_person_property_raises_error(self):
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
        with self.assertRaises(ResolutionError) as cm:
            self._compile_select("SELECT person.properties.secret_person_field FROM events")
        assert "secret_person_field" in str(cm.exception)

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
        with self.assertRaises(ResolutionError):
            prepare_and_print_ast(node, context=context, dialect="clickhouse")

    def test_non_property_fields_not_affected(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        sql = self._compile_select("SELECT event, timestamp FROM events")
        assert "event" in sql
        assert "timestamp" in sql

    def test_denied_property_in_where_raises_error(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        with self.assertRaises(ResolutionError):
            self._compile_select("SELECT event FROM events WHERE properties.secret_field = 'foo'")

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

    def test_error_is_indistinguishable_from_nonexistent_field(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # the error for a restricted property should use the exact same message format
        # as the standard ResolutionError for accessing a child on a non-traversable field,
        # so that an attacker cannot distinguish restricted from non-existent
        with self.assertRaises(ResolutionError) as cm:
            self._compile_select("SELECT properties.secret_field FROM events")
        error_msg = str(cm.exception)
        assert error_msg == 'Can not access property "secret_field" on field "properties".'
        # the error should not mention restriction-specific words
        for forbidden_word in ["restricted", "denied", "permission", "not allowed"]:
            assert forbidden_word not in error_msg.lower(), f"Error message leaks access control info: '{error_msg}'"
