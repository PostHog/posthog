from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.customer_analytics.backend.facade import (
    api as facade,
    contracts,
)
from products.customer_analytics.backend.logic.custom_property_values import (
    MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES,
    VALUE_SUGGESTIONS_LIMIT,
    CustomPropertyDefinitionNotFound,
    CustomPropertyValueConflict,
    InvalidCustomPropertyValue,
    list_active_custom_property_values,
    list_custom_property_value_suggestions,
    record_last_slack_message_at,
    set_account_custom_properties_by_id,
    set_custom_property_value,
    set_synced_custom_property_value,
)
from products.customer_analytics.backend.models import (
    CANONICAL_LAST_SLACK_MESSAGE_AT,
    Account,
    CustomPropertyDefinition,
    CustomPropertyValue,
    DisplayType,
)
from products.customer_analytics.backend.models.custom_property_value import ACTIVE_VALUE_CONSTRAINT_NAME
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.workflows.backend.models import HogFlow

LOGIC_MODULE = "products.customer_analytics.backend.logic.custom_property_values"

SELECT_OPTIONS = [
    {"id": "opt-1", "label": "Enterprise", "color": "preset-1"},
    {"id": "opt-2", "label": "Startup", "color": "preset-2"},
]


class TestSetCustomPropertyValue(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id)

    def _create_property_definition(
        self, display_type: str = DisplayType.TEXT, name: str = "Prop"
    ) -> CustomPropertyDefinition:
        return create_custom_property_definition(team_id=self.team.id, name=name, display_type=display_type)

    def _set(self, *, definition: CustomPropertyDefinition, value: object) -> CustomPropertyValue:
        return set_custom_property_value(
            team_id=self.team.id,
            account_id=self.account.id,
            definition_id=definition.id,
            value=value,
            created_by_id=self.user.id,
        )

    @parameterized.expand(
        [
            ("text", DisplayType.TEXT, "enterprise", "value_str", "enterprise"),
            ("link", DisplayType.LINK, "https://example.com/customer", "value_str", "https://example.com/customer"),
            ("number_int", DisplayType.NUMBER, 12, "value_num", 12.0),
            ("number_decimal", DisplayType.NUMBER, 9.99, "value_num", 9.99),
            ("number_string", DisplayType.NUMBER, "42", "value_num", 42.0),
            ("currency", DisplayType.CURRENCY, 1000, "value_num", 1000.0),
            ("percent", DisplayType.PERCENT, 0.5, "value_num", 0.5),
            ("boolean_true", DisplayType.BOOLEAN, True, "value_bool", True),
            ("boolean_true_string", DisplayType.BOOLEAN, "true", "value_bool", True),
            ("boolean_false_string", DisplayType.BOOLEAN, "FALSE", "value_bool", False),
            (
                "datetime",
                DisplayType.DATETIME,
                "2026-01-01T12:00:00+00:00",
                "value_datetime",
                datetime(2026, 1, 1, 12, tzinfo=UTC),
            ),
            (
                "datetime_z",
                DisplayType.DATETIME,
                "2026-01-01T12:00:00Z",
                "value_datetime",
                datetime(2026, 1, 1, 12, tzinfo=UTC),
            ),
            ("date_only", DisplayType.DATE, "2026-01-01", "value_datetime", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
    )
    def test_writes_coerced_value_into_the_right_column(self, _name, display_type, value, column, expected):
        definition = self._create_property_definition(display_type=display_type, name=_name)

        instance = self._set(definition=definition, value=value)
        instance.refresh_from_db()

        assert getattr(instance, column) == expected
        assert instance.created_by_id == self.user.id
        assert instance.is_deleted is False
        # only the target column is populated
        other_columns = {"value_str", "value_bool", "value_num", "value_datetime"} - {column}
        assert all(getattr(instance, other) is None for other in other_columns)

    @parameterized.expand(
        [
            ("numeric_from_text", DisplayType.NUMBER, "abc"),
            ("numeric_from_bool", DisplayType.NUMBER, True),
            ("numeric_from_nan_string", DisplayType.NUMBER, "nan"),
            ("numeric_from_inf_string", DisplayType.NUMBER, "inf"),
            ("numeric_from_negative_inf_string", DisplayType.NUMBER, "-inf"),
            ("numeric_from_nan_float", DisplayType.NUMBER, float("nan")),
            ("numeric_from_inf_float", DisplayType.NUMBER, float("inf")),
            ("boolean_from_arbitrary_string", DisplayType.BOOLEAN, "yes"),
            ("boolean_from_int", DisplayType.BOOLEAN, 1),
            ("datetime_from_unparseable", DisplayType.DATETIME, "not a date"),
            ("datetime_from_number", DisplayType.DATETIME, 123),
            ("text_from_list", DisplayType.TEXT, ["nope"]),
            ("link_with_unsafe_scheme", DisplayType.LINK, "javascript:alert(1)"),
            ("link_without_url", DisplayType.LINK, "example.com"),
        ]
    )
    def test_rejects_values_that_do_not_match_the_type(self, _name, display_type, value):
        definition = self._create_property_definition(display_type=display_type, name=_name)

        with pytest.raises(InvalidCustomPropertyValue):
            self._set(definition=definition, value=value)

        assert not CustomPropertyValue.objects.for_team(self.team.id).filter(definition=definition).exists()

    def test_select_writes_matching_label_into_value_str(self):
        definition = create_custom_property_definition(
            team_id=self.team.id, name="Tier", display_type=DisplayType.SELECT, options=SELECT_OPTIONS
        )

        instance = self._set(definition=definition, value="Enterprise")
        instance.refresh_from_db()

        assert instance.value_str == "Enterprise"
        assert instance.value_num is None and instance.value_bool is None and instance.value_datetime is None

    @parameterized.expand(
        [
            ("unknown_label", "Mid-market"),
            ("case_mismatch", "enterprise"),
            ("empty_string", ""),
            ("number", 3),
            ("boolean", True),
            ("list", ["Enterprise"]),
        ]
    )
    def test_select_rejects_values_not_matching_an_option(self, _name, value):
        definition = create_custom_property_definition(
            team_id=self.team.id, name=f"Tier {_name}", display_type=DisplayType.SELECT, options=SELECT_OPTIONS
        )

        with pytest.raises(InvalidCustomPropertyValue):
            self._set(definition=definition, value=value)

        assert not CustomPropertyValue.objects.for_team(self.team.id).filter(definition=definition).exists()

    def test_naive_datetime_is_stored_as_aware_utc(self):
        definition = self._create_property_definition(display_type=DisplayType.DATETIME)

        instance = self._set(definition=definition, value=datetime(2026, 6, 18, 12))
        instance.refresh_from_db()

        assert instance.value_datetime is not None
        assert timezone.is_aware(instance.value_datetime)
        assert instance.value_datetime == datetime(2026, 6, 18, 12, tzinfo=UTC)

    def test_unknown_definition_raises(self):
        with pytest.raises(CustomPropertyDefinitionNotFound):
            set_custom_property_value(
                team_id=self.team.id, account_id=self.account.id, definition_id=uuid4(), value="x"
            )

    def test_account_from_another_team_is_rejected(self):
        other_team = Team.objects.create(organization=self.organization)
        other_account = create_account(team_id=other_team.id)
        definition = self._create_property_definition()

        with pytest.raises(Account.DoesNotExist):
            set_custom_property_value(
                team_id=self.team.id, account_id=other_account.id, definition_id=definition.id, value="x"
            )

    def test_setting_a_new_value_soft_deletes_the_previous_and_keeps_history(self):
        definition = self._create_property_definition()

        first = self._set(definition=definition, value="starter")
        second = self._set(definition=definition, value="enterprise")

        rows = CustomPropertyValue.objects.for_team(self.team.id).filter(account=self.account, definition=definition)
        assert rows.count() == 2
        assert rows.get(is_deleted=False) == second

        first.refresh_from_db()
        assert first.is_deleted is True

    def test_regular_same_value_still_adds_history(self):
        definition = self._create_property_definition()

        self._set(definition=definition, value="enterprise")
        self._set(definition=definition, value="enterprise")

        assert (
            CustomPropertyValue.objects.for_team(self.team.id)
            .filter(account=self.account, definition=definition)
            .count()
            == 2
        )

    def test_synced_same_value_does_not_add_history(self):
        definition = self._create_property_definition()
        self._set(definition=definition, value="enterprise")

        changed = set_synced_custom_property_value(
            team_id=self.team.id,
            account_id=self.account.id,
            definition=definition,
            value="enterprise",
        )

        assert changed is False
        assert (
            CustomPropertyValue.objects.for_team(self.team.id)
            .filter(account=self.account, definition=definition)
            .count()
            == 1
        )

    def test_list_active_returns_only_current_values(self):
        plan = self._create_property_definition(name="Plan")
        seats = self._create_property_definition(name="Seats", display_type=DisplayType.NUMBER)

        self._set(definition=plan, value="starter")
        self._set(definition=plan, value="enterprise")  # supersedes the starter row
        self._set(definition=seats, value=42)

        active = list_active_custom_property_values(team_id=self.team.id, account_id=self.account.id)

        assert {(v.definition_id, v.value_str, v.value_num) for v in active} == {
            (plan.id, "enterprise", None),
            (seats.id, None, 42.0),
        }

    @patch(f"{LOGIC_MODULE}.CustomPropertyValue")
    def test_losing_the_active_value_race_surfaces_as_a_conflict(self, mock_value_model):
        definition = self._create_property_definition()
        mock_value_model.objects.for_team.return_value.create.side_effect = IntegrityError(
            f'duplicate key value violates unique constraint "{ACTIVE_VALUE_CONSTRAINT_NAME}"'
        )

        with pytest.raises(CustomPropertyValueConflict):
            self._set(definition=definition, value="enterprise")

    @patch(f"{LOGIC_MODULE}.CustomPropertyValue")
    def test_other_integrity_errors_are_not_masked_as_conflicts(self, mock_value_model):
        definition = self._create_property_definition()
        mock_value_model.objects.for_team.return_value.create.side_effect = IntegrityError(
            'new row violates check constraint "custom_property_value_exactly_one_value"'
        )

        with pytest.raises(IntegrityError):
            self._set(definition=definition, value="enterprise")


class TestSetAccountCustomPropertiesById(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id)

    def test_sets_multiple_values_resolving_each_definition_by_id(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=DisplayType.TEXT)
        seats = create_custom_property_definition(team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER)

        rows = set_account_custom_properties_by_id(
            team_id=self.team.id,
            account_id=self.account.id,
            properties={str(plan.id): "enterprise", str(seats.id): "42"},
        )

        assert {(r.definition_id, r.value_str, r.value_num) for r in rows} == {
            (plan.id, "enterprise", None),
            (seats.id, None, 42.0),
        }

    def test_unknown_id_raises_carrying_the_id(self):
        missing = uuid4()
        with pytest.raises(CustomPropertyDefinitionNotFound) as exc_info:
            set_account_custom_properties_by_id(
                team_id=self.team.id, account_id=self.account.id, properties={str(missing): "x"}
            )
        assert exc_info.value.identifier == str(missing)

    def test_invalid_value_raises_carrying_the_id(self):
        seats = create_custom_property_definition(team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER)
        with pytest.raises(InvalidCustomPropertyValue) as exc_info:
            set_account_custom_properties_by_id(
                team_id=self.team.id, account_id=self.account.id, properties={str(seats.id): "not a number"}
            )
        assert exc_info.value.field == str(seats.id)


class TestListCustomPropertyValueSuggestions(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id)

    def _set(self, definition: CustomPropertyDefinition, value: object, account: Account | None = None) -> None:
        set_custom_property_value(
            team_id=self.team.id,
            account_id=(account or self.account).id,
            definition_id=definition.id,
            value=value,
        )

    def _suggestions(self, definition_id: str | UUID, search: str | None = None) -> list[str]:
        return list_custom_property_value_suggestions(team_id=self.team.id, definition_id=definition_id, search=search)

    def test_select_returns_option_labels_filtered_by_search(self):
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="Tier",
            display_type=DisplayType.SELECT,
            options=[*SELECT_OPTIONS, {"id": "opt-3", "color": "preset-3"}],  # unlabeled option must not suggest
        )
        assert self._suggestions(definition.id) == ["Enterprise", "Startup"]
        assert self._suggestions(definition.id, search="ENT") == ["Enterprise"]

    def test_text_returns_distinct_active_values_only(self):
        definition = create_custom_property_definition(team_id=self.team.id, name="Region")
        other_account = create_account(team_id=self.team.id, name="Other", external_id="other-ext")
        self._set(definition, "emea")
        self._set(definition, "apac")  # supersedes "emea" — the soft-deleted row must not suggest
        self._set(definition, "amer", account=other_account)
        assert self._suggestions(definition.id) == ["amer", "apac"]
        assert self._suggestions(definition.id, search="ap") == ["apac"]

    def test_boolean_suggests_true_false(self):
        definition = create_custom_property_definition(
            team_id=self.team.id, name="Active", display_type=DisplayType.BOOLEAN
        )
        assert self._suggestions(definition.id) == ["true", "false"]

    def test_numeric_values_render_like_clickhouse_tostring(self):
        definition = create_custom_property_definition(
            team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER
        )
        other_account = create_account(team_id=self.team.id, name="Other2", external_id="other-ext-2")
        self._set(definition, 10.0)
        self._set(definition, 2.5, account=other_account)
        assert self._suggestions(definition.id) == ["2.5", "10"]

    def test_numeric_search_matches_values_beyond_the_limit_window(self):
        definition = create_custom_property_definition(
            team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER
        )
        accounts = Account.objects.unscoped().bulk_create(
            Account(team_id=self.team.id, name=f"Account {i}") for i in range(VALUE_SUGGESTIONS_LIMIT + 10)
        )
        CustomPropertyValue.objects.unscoped().bulk_create(
            CustomPropertyValue(team_id=self.team.id, account=account, definition=definition, value_num=float(i))
            for i, account in enumerate(accounts)
        )
        # The match sorts after the first VALUE_SUGGESTIONS_LIMIT values — the search must not be
        # applied to a pre-sliced window.
        assert self._suggestions(definition.id, search=str(VALUE_SUGGESTIONS_LIMIT + 5)) == [
            str(VALUE_SUGGESTIONS_LIMIT + 5)
        ]

    def test_non_finite_numeric_rows_are_skipped(self):
        definition = create_custom_property_definition(
            team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER
        )
        # Write-path coercion rejects non-finite values, so plant a stray row directly; it must be
        # skipped rather than crash the suggestions.
        stray_account = create_account(team_id=self.team.id, name="Stray", external_id="stray-ext")
        CustomPropertyValue.objects.unscoped().create(
            team_id=self.team.id, account=stray_account, definition=definition, value_num=float("inf")
        )
        self._set(definition, 7.0)
        assert self._suggestions(definition.id) == ["7"]

    @parameterized.expand([("unknown_uuid", str(uuid4())), ("malformed", "not-a-uuid")])
    def test_unknown_definition_returns_empty(self, _name, definition_id):
        assert self._suggestions(definition_id) == []


class TestCustomPropertyValueFacade(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id)

    @parameterized.expand(
        [
            ("text", DisplayType.TEXT, "enterprise", "enterprise"),
            ("number", DisplayType.NUMBER, 9.99, 9.99),
            ("boolean", DisplayType.BOOLEAN, True, True),
            (
                "datetime",
                DisplayType.DATETIME,
                "2026-01-01T12:00:00Z",
                datetime(2026, 1, 1, 12, tzinfo=UTC),
            ),
        ]
    )
    def test_set_returns_a_contract_with_the_typed_value(self, _name, display_type, value, expected_value):
        definition = create_custom_property_definition(team_id=self.team.id, name=_name, display_type=display_type)

        result = facade.set_custom_property_value(self.team.id, self.account.id, definition.id, value, actor=self.user)

        assert isinstance(result, contracts.CustomPropertyValue)
        assert result.value == expected_value
        # the union must not coerce across types (e.g. bool True -> 1.0)
        assert type(result.value) is type(expected_value)
        assert result.account_id == self.account.id
        assert result.definition_id == definition.id
        assert result.created_by_id == self.user.id

    def test_list_active_returns_contracts(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan")
        facade.set_custom_property_value(self.team.id, self.account.id, plan.id, "enterprise")

        result = facade.list_active_custom_property_values(self.team.id, self.account.id)

        assert len(result) == 1
        assert isinstance(result[0], contracts.CustomPropertyValue)
        assert result[0].value == "enterprise"
        assert result[0].definition_id == plan.id


class TestRecordLastSlackMessageAt(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id, _properties={"slack_channel_id": "C_ACME"})
        self.at = datetime(2026, 7, 29, 12, tzinfo=UTC)

    def _record(self, timestamp: datetime) -> bool:
        return record_last_slack_message_at(team_id=self.team.id, account_id=self.account.id, timestamp=timestamp)

    def _active_values(self) -> list[datetime | None]:
        return list(
            CustomPropertyValue.objects.for_team(self.team.id)
            .filter(is_deleted=False)
            .values_list("value_datetime", flat=True)
        )

    def _row_count(self) -> int:
        return CustomPropertyValue.objects.for_team(self.team.id).count()

    def test_first_message_creates_the_canonical_definition(self):
        assert self._record(self.at) is True

        definition = CustomPropertyDefinition.objects.for_team(self.team.id).get(name=CANONICAL_LAST_SLACK_MESSAGE_AT)
        assert definition.display_type == DisplayType.DATETIME
        assert definition.created_by_id is None
        assert self._active_values() == [self.at]

    def test_message_within_the_interval_does_not_write(self):
        self._record(self.at)

        assert self._record(self.at + MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES - timedelta(minutes=1)) is False
        assert self._active_values() == [self.at]
        assert self._row_count() == 1

    def test_message_after_the_interval_supersedes_the_value(self):
        self._record(self.at)
        later = self.at + MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES

        assert self._record(later) is True
        assert self._active_values() == [later]
        # The superseded row stays for history.
        assert self._row_count() == 2

    def test_out_of_order_message_does_not_move_the_value_backwards(self):
        self._record(self.at)

        assert self._record(self.at - timedelta(days=1)) is False
        assert self._active_values() == [self.at]

    @patch(f"{LOGIC_MODULE}._set_value")
    def test_losing_the_active_row_race_retries_instead_of_dropping_the_timestamp(self, mock_set_value):
        later = self.at + MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES
        mock_set_value.side_effect = [CustomPropertyValueConflict("rival won the active row"), None]

        assert self._record(later) is True
        assert mock_set_value.call_count == 2

    @patch(f"{LOGIC_MODULE}._set_value")
    def test_a_rival_storing_a_newer_value_stops_the_retry(self, mock_set_value):
        # The rival's value lands before the retry re-reads, so the retry must skip rather than
        # drag the stored value back to this older message.
        newer = self.at + 2 * MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES

        def store_newer_then_conflict(**kwargs):
            self._set_active_value(newer)
            raise CustomPropertyValueConflict("rival won the active row")

        mock_set_value.side_effect = store_newer_then_conflict

        assert self._record(self.at + MIN_INTERVAL_BETWEEN_LAST_SLACK_MESSAGE_WRITES) is False
        assert self._active_values() == [newer]
        # The retry re-read the rival's value and skipped, rather than writing again.
        assert mock_set_value.call_count == 1

    def _set_active_value(self, timestamp: datetime) -> None:
        """Store a value the way a rival task would. Writes through the ORM, not the logic's own
        write path — this test doubles that path, so going through it would store nothing."""
        definition = CustomPropertyDefinition.objects.for_team(self.team.id).get(name=CANONICAL_LAST_SLACK_MESSAGE_AT)
        rows = CustomPropertyValue.objects.for_team(self.team.id)
        rows.filter(account_id=self.account.id, definition_id=definition.id, is_deleted=False).update(is_deleted=True)
        rows.create(
            team_id=self.team.id,
            account_id=self.account.id,
            definition_id=definition.id,
            value_datetime=timestamp,
        )

    def test_a_conflicting_definition_type_rejects_the_write(self):
        create_custom_property_definition(
            team_id=self.team.id, name=CANONICAL_LAST_SLACK_MESSAGE_AT, display_type=DisplayType.TEXT
        )

        with pytest.raises(InvalidCustomPropertyValue):
            self._record(self.at)

    def test_facade_records_the_value(self):
        assert (
            facade.record_last_slack_message_at(team_id=self.team.id, account_id=self.account.id, timestamp=self.at)
            is True
        )
        assert self._active_values() == [self.at]


class TestCanonicalCustomPropertyDefinition(BaseTest):
    def setUp(self):
        super().setUp()
        self.definition = create_custom_property_definition(
            team_id=self.team.id, name=CANONICAL_LAST_SLACK_MESSAGE_AT, display_type=DisplayType.DATETIME
        )

    def _update(self, fields: dict) -> None:
        with team_scope(self.team.id):
            facade.update_custom_property_definition(
                team_id=self.team.id,
                definition_id=str(self.definition.id),
                fields=fields,
                organization_id=self.organization.id,
                user=self.user,
                was_impersonated=False,
            )

    @parameterized.expand([("name", "Something else"), ("display_type", DisplayType.TEXT.value)])
    def test_posthog_owned_fields_cannot_be_changed(self, field, value):
        with pytest.raises(facade.CanonicalCustomPropertyReadOnlyError):
            self._update({field: value})

        self.definition.refresh_from_db()
        assert self.definition.name == CANONICAL_LAST_SLACK_MESSAGE_AT
        assert self.definition.display_type == DisplayType.DATETIME

    def test_the_rest_of_the_definition_stays_editable(self):
        self._update({"description": "When the customer last posted in Slack"})

        self.definition.refresh_from_db()
        assert self.definition.description == "When the customer last posted in Slack"

    @parameterized.expand([(CANONICAL_LAST_SLACK_MESSAGE_AT, True), ("Plan", False)])
    def test_the_view_marks_canonical_definitions(self, name, expected):
        definition = self.definition if expected else create_custom_property_definition(team_id=self.team.id, name=name)

        with team_scope(self.team.id):
            view = facade.get_custom_property_definition(
                self.team.id, str(definition.id), user_access_control=self._uac()
            )

        assert view is not None
        assert view.is_canonical is expected

    def _uac(self):
        uac = MagicMock()
        uac.check_access_level_for_resource.return_value = True
        return uac

    def test_a_non_canonical_definition_can_be_renamed(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan")
        with team_scope(self.team.id):
            facade.update_custom_property_definition(
                team_id=self.team.id,
                definition_id=str(plan.id),
                fields={"name": "Tier"},
                organization_id=self.organization.id,
                user=self.user,
                was_impersonated=False,
            )

        plan.refresh_from_db()
        assert plan.name == "Tier"


class TestSetExternalAccountCustomProperties(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id, external_id="acme-1")

    def test_sets_values_by_id_and_returns_contracts(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=DisplayType.TEXT)
        seats = create_custom_property_definition(team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER)

        result = facade.set_external_account_custom_properties(
            self.team.id, "acme-1", properties={str(plan.id): "enterprise", str(seats.id): 42}
        )

        assert result.error is None
        assert result.values is not None
        assert {(v.value) for v in result.values} == {"enterprise", 42.0}

    def test_unknown_external_id_returns_account_not_found(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan")
        result = facade.set_external_account_custom_properties(self.team.id, "missing", properties={str(plan.id): "x"})
        assert result.error == contracts.ExternalAccountCustomPropertiesError.ACCOUNT_NOT_FOUND

    def test_maps_unknown_definition_to_error_with_offending_id(self):
        missing = uuid4()
        result = facade.set_external_account_custom_properties(self.team.id, "acme-1", properties={str(missing): "x"})
        assert result.values is None
        assert result.error == contracts.ExternalAccountCustomPropertiesError.DEFINITION_NOT_FOUND
        assert result.error_field == str(missing)

    def test_maps_invalid_value_to_error_with_offending_id(self):
        seats = create_custom_property_definition(team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER)
        result = facade.set_external_account_custom_properties(
            self.team.id, "acme-1", properties={str(seats.id): "abc"}
        )
        assert result.values is None
        assert result.error == contracts.ExternalAccountCustomPropertiesError.INVALID_VALUE
        assert result.error_field == str(seats.id)

    def test_batch_is_all_or_nothing(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=DisplayType.TEXT)
        seats = create_custom_property_definition(team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER)

        result = facade.set_external_account_custom_properties(
            self.team.id, "acme-1", properties={str(plan.id): "enterprise", str(seats.id): "not a number"}
        )

        assert result.error == contracts.ExternalAccountCustomPropertiesError.INVALID_VALUE
        # The good "Plan" write must roll back with the failed "Seats" write — nothing persists.
        assert not CustomPropertyValue.objects.for_team(self.team.id).filter(account=self.account).exists()


class TestCustomPropertyDefinitionReferences(BaseTest):
    def _uac(self, *, can_read_workflows: bool = True) -> MagicMock:
        uac = MagicMock()
        uac.check_access_level_for_resource.return_value = can_read_workflows
        return uac

    def _create_workflow_setting(self, definition_id: str, *, name: str = "Onboarding", status: str = "active"):
        return HogFlow.objects.create(
            team=self.team,
            name=name,
            status=status,
            actions=[
                {
                    "type": "function",
                    "config": {
                        "template_id": "template-posthog-update-account-property",
                        "inputs": {"properties": {"value": {definition_id: "{event.properties.x}"}}},
                    },
                }
            ],
        )

    def test_list_attaches_workflow_references_matched_by_id(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan")
        create_custom_property_definition(team_id=self.team.id, name="Unused")
        workflow = self._create_workflow_setting(str(plan.id))

        with team_scope(self.team.id):
            page, _ = facade.list_custom_property_definitions(
                self.team.id, offset=0, limit=50, user_access_control=self._uac()
            )
        by_id = {view.id: view for view in page}

        assert [(r.id, r.name, r.status, r.type) for r in by_id[plan.id].references] == [
            (str(workflow.id), "Onboarding", "active", "workflow")
        ]
        # A definition no workflow references carries an empty list.
        unused = next(v for v in page if v.name == "Unused")
        assert unused.references == []

    def test_reference_matches_id_not_name(self):
        # A workflow keyed by a stale/foreign id must not attach to a same-named definition.
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self._create_workflow_setting(str(uuid4()))

        with team_scope(self.team.id):
            page, _ = facade.list_custom_property_definitions(
                self.team.id, offset=0, limit=50, user_access_control=self._uac()
            )

        assert next(v for v in page if v.id == plan.id).references == []

    def test_get_attaches_workflow_references_for_single_definition(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan")
        workflow = self._create_workflow_setting(str(plan.id))

        with team_scope(self.team.id):
            view = facade.get_custom_property_definition(self.team.id, str(plan.id), user_access_control=self._uac())

        assert view is not None
        assert [(r.id, r.name, r.status, r.type) for r in view.references] == [
            (str(workflow.id), "Onboarding", "active", "workflow")
        ]

    def test_references_hidden_without_workflow_read_access(self):
        # references expose HogFlow metadata, so a caller without hog_flow read access sees none.
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self._create_workflow_setting(str(plan.id))

        with team_scope(self.team.id):
            page, _ = facade.list_custom_property_definitions(
                self.team.id, offset=0, limit=50, user_access_control=self._uac(can_read_workflows=False)
            )
            view = facade.get_custom_property_definition(
                self.team.id, str(plan.id), user_access_control=self._uac(can_read_workflows=False)
            )

        assert next(v for v in page if v.id == plan.id).references == []
        assert view is not None
        assert view.references == []
