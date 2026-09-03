from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from django.test import override_settings

from parameterized import parameterized

from posthog.api.tagged_item import set_tags_on_object
from posthog.models.team import Team

from products.customer_analytics.backend.facade.api import (
    count_accounts_for_audience,
    list_account_external_ids_for_audience,
)
from products.customer_analytics.backend.logic import relationships as relationships_logic
from products.customer_analytics.backend.models import AccountRelationshipDefinition, CustomPropertyValue
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.workflows.backend.services.account_audience import (
    AccountAudienceCustomPropertyFilter,
    AccountAudienceFilters,
)


@override_settings(IN_UNIT_TESTING=True)
class TestAccountAudience(ClickhouseTestMixin, NonAtomicBaseTest):
    def _list(self, filters: AccountAudienceFilters | None = None, cursor: str | None = None, limit: int = 100):
        return list_account_external_ids_for_audience(
            self.team, filters or AccountAudienceFilters(), cursor=cursor, limit=limit
        )

    def _custom_property_filters(self, definition_id, operator: str, value=None) -> AccountAudienceFilters:
        return AccountAudienceFilters(
            custom_properties=(
                AccountAudienceCustomPropertyFilter(definition_id=definition_id, operator=operator, value=value),
            )
        )

    def test_pages_external_ids_in_order_and_skips_accounts_without_one(self):
        create_account(team_id=self.team.id, name="C", external_id="c1")
        create_account(team_id=self.team.id, name="A", external_id="a1")
        create_account(team_id=self.team.id, name="B", external_id="b1")
        create_account(team_id=self.team.id, name="No key", external_id=None)

        first_page = self._list(limit=2)
        assert first_page == ["a1", "b1"]
        assert self._list(cursor=first_page[-1], limit=2) == ["c1"]

    def test_scopes_to_team(self):
        create_account(team_id=self.team.id, name="Mine", external_id="mine")
        other_team = Team.objects.create(organization=self.organization)
        create_account(team_id=other_team.id, name="Theirs", external_id="theirs")

        assert self._list() == ["mine"]

    def test_excludes_ignored_accounts_from_list_and_count(self):
        create_account(team_id=self.team.id, name="Tracked", external_id="tracked")
        create_account(
            team_id=self.team.id,
            name="Ignored",
            external_id="ignored",
            ignored_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert self._list() == ["tracked"]
        assert count_accounts_for_audience(self.team, AccountAudienceFilters()) == 1

    def test_tag_filter_narrows(self):
        tagged = create_account(team_id=self.team.id, name="Tagged", external_id="tagged")
        create_account(team_id=self.team.id, name="Untagged", external_id="untagged")
        set_tags_on_object(["vip"], tagged)

        assert self._list(AccountAudienceFilters(tag_names=("vip",))) == ["tagged"]

    def test_assignment_filters_narrow(self):
        holder = self._create_user("holder@x.com")
        assigned = create_account(team_id=self.team.id, name="Assigned", external_id="assigned")
        create_account(team_id=self.team.id, name="Unassigned", external_id="unassigned")
        definition, _ = AccountRelationshipDefinition.objects.for_team(self.team.id).get_or_create(
            team_id=self.team.id, name="CSM"
        )
        relationships_logic.assign(
            team_id=self.team.id, account=assigned, definition=definition, user=holder, created_by=holder
        )

        assert self._list(AccountAudienceFilters(assigned_to_user_ids=(holder.id,))) == ["assigned"]
        assert self._list(AccountAudienceFilters(all_roles_unassigned=True)) == ["unassigned"]

    @parameterized.expand(
        [
            ("exact_string", "text", {"value_str": "Enterprise"}, {"value_str": "Startup"}, "exact", ["Enterprise"]),
            (
                "exact_multi_value",
                "text",
                {"value_str": "Enterprise"},
                {"value_str": "Startup"},
                "exact",
                ["Enterprise", "Mid-market"],
            ),
            ("icontains", "text", {"value_str": "Enterprise plan"}, {"value_str": "Startup"}, "icontains", ["enter"]),
            ("regex", "text", {"value_str": "tier-9"}, {"value_str": "tier-x"}, "regex", ["tier-[0-9]+"]),
            ("numeric_gt", "number", {"value_num": 100}, {"value_num": 5}, "gt", [50]),
            ("boolean_exact", "boolean", {"value_bool": True}, {"value_bool": False}, "exact", ["true"]),
            (
                "date_before",
                "datetime",
                {"value_datetime": datetime(2026, 1, 10, tzinfo=UTC)},
                {"value_datetime": datetime(2026, 6, 10, tzinfo=UTC)},
                "is_date_before",
                ["2026-03-01"],
            ),
        ]
    )
    def test_custom_property_operators_narrow(self, _name, display_type, match_value, other_value, operator, value):
        definition = create_custom_property_definition(team_id=self.team.id, name="Prop", display_type=display_type)
        match = create_account(team_id=self.team.id, name="Match", external_id="match")
        other = create_account(team_id=self.team.id, name="Other", external_id="other")
        CustomPropertyValue.objects.unscoped().create(
            team_id=self.team.id, account=match, definition=definition, **match_value
        )
        CustomPropertyValue.objects.unscoped().create(
            team_id=self.team.id, account=other, definition=definition, **other_value
        )

        assert self._list(self._custom_property_filters(definition.id, operator, value)) == ["match"]

    def test_is_not_keeps_accounts_without_a_value(self):
        definition = create_custom_property_definition(team_id=self.team.id, name="Tier")
        excluded = create_account(team_id=self.team.id, name="Excluded", external_id="excluded")
        create_account(team_id=self.team.id, name="Unset", external_id="unset")
        CustomPropertyValue.objects.unscoped().create(
            team_id=self.team.id, account=excluded, definition=definition, value_str="Enterprise"
        )

        assert self._list(self._custom_property_filters(definition.id, "is_not", ["Enterprise"])) == ["unset"]

    def test_is_set_and_is_not_set(self):
        definition = create_custom_property_definition(team_id=self.team.id, name="Tier")
        with_value = create_account(team_id=self.team.id, name="With", external_id="with")
        create_account(team_id=self.team.id, name="Without", external_id="without")
        CustomPropertyValue.objects.unscoped().create(
            team_id=self.team.id, account=with_value, definition=definition, value_str="x"
        )

        assert self._list(self._custom_property_filters(definition.id, "is_set")) == ["with"]
        assert self._list(self._custom_property_filters(definition.id, "is_not_set")) == ["without"]

    def test_unknown_definition_id_fails_resolution(self):
        # Dropping the predicate would silently broaden the audience to every account.
        create_account(team_id=self.team.id, name="A", external_id="a1")

        with self.assertRaisesRegex(ValueError, "deleted or unknown custom property"):
            self._list(self._custom_property_filters(uuid4(), "exact", ["x"]))

    def test_type_incompatible_value_fails_resolution(self):
        definition = create_custom_property_definition(team_id=self.team.id, name="MRR", display_type="number")
        create_account(team_id=self.team.id, name="A", external_id="a1")

        with self.assertRaisesRegex(ValueError, "incompatible"):
            self._list(self._custom_property_filters(definition.id, "exact", ["not-a-number"]))

    def test_count_matches_list(self):
        tagged = create_account(team_id=self.team.id, name="Tagged", external_id="tagged")
        create_account(team_id=self.team.id, name="Untagged", external_id="untagged")
        create_account(team_id=self.team.id, name="No key", external_id=None)
        set_tags_on_object(["vip"], tagged)

        assert count_accounts_for_audience(self.team, AccountAudienceFilters()) == 2
        filters = AccountAudienceFilters(tag_names=("vip",))
        assert count_accounts_for_audience(self.team, filters) == len(self._list(filters))
