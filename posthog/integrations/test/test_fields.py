from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import serializers

from posthog.integrations.contracts import SOURCE_MARKER_CONFIG_KEY
from posthog.integrations.enums import AuthType
from posthog.integrations.fields import IntegrationReferenceField
from posthog.models import Team
from posthog.models.comment.slack_thread import CommentSlackThread
from posthog.models.integration import ANY, Integration


class _Serializer(serializers.Serializer):
    integration = IntegrationReferenceField()
    github = IntegrationReferenceField(kinds=["github"], required=False, allow_null=True)
    github_any = IntegrationReferenceField(kinds=["github"], auth_types="any", required=False)
    github_token = IntegrationReferenceField(kinds=["github"], auth_types=[AuthType.TOKEN], required=False)


class TestIntegrationReferenceField(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.slack = Integration.objects._with_auth(ANY).create(team=self.team, kind="slack", integration_id="s")
        self.github_oauth = Integration.objects._with_auth(ANY).create(
            team=self.team, kind="github", integration_id="o"
        )
        self.github = Integration.objects._with_auth(ANY).create(
            team=self.team, kind="github", integration_id="g", config={"auth_type": "token"}
        )
        self.github_source_row = Integration.objects._with_auth(ANY).create(
            team=self.team,
            kind="github",
            integration_id="gs",
            config={"auth_type": "token", SOURCE_MARKER_CONFIG_KEY: "Github"},
        )
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self.other = Integration.objects._with_auth(ANY).create(team=other_team, kind="slack", integration_id="s")

    def _validate(self, data: dict[str, Any], context: dict[str, Any] | None = None) -> _Serializer:
        serializer = _Serializer(data=data, context={"team_id": self.team.id} if context is None else context)
        serializer.is_valid()
        return serializer

    @parameterized.expand(
        [
            ("int", lambda self: self.slack.id),
            ("string", lambda self: str(self.slack.id)),
        ]
    )
    def test_accepts_an_id_of_the_team(self, _name: str, value: Any) -> None:
        serializer = self._validate({"integration": value(self), "github": self.github_oauth.id})

        assert serializer.errors == {}
        assert serializer.validated_data == {"integration": self.slack, "github": self.github_oauth}

    @parameterized.expand(
        [
            ("no_kinds_accepts_every_auth_type", "integration", "github", None),
            ("default_accepts_the_kind_default", "github", "github_oauth", None),
            ("default_refuses_another_auth_type", "github", "github", "does_not_exist"),
            ("any_accepts_the_kind_default", "github_any", "github_oauth", None),
            ("any_accepts_another_auth_type", "github_any", "github", None),
            ("any_refuses_a_source_row", "github_any", "github_source_row", "does_not_exist"),
            ("listed_accepts_its_auth_type", "github_token", "github", None),
            ("listed_refuses_the_kind_default", "github_token", "github_oauth", "does_not_exist"),
        ]
    )
    def test_auth_types(self, _name: str, field: str, row: str, error_code: str | None) -> None:
        serializer = self._validate({"integration": self.slack.id, field: getattr(self, row).id})

        if error_code is None:
            assert serializer.validated_data[field] == getattr(self, row)
        else:
            assert [error.code for error in serializer.errors[field]] == [error_code]

    @parameterized.expand(
        [
            ("allow_null", "github", None),
            ("not_allow_null", "github_any", "null"),
            ("not_allow_null_without_kinds", "integration", "null"),
        ]
    )
    def test_an_empty_string_means_null(self, _name: str, field: str, error_code: str | None) -> None:
        serializer = self._validate({"integration": self.slack.id, field: ""})

        if error_code is None:
            assert serializer.errors == {}
            assert serializer.validated_data[field] is None
        else:
            assert [error.code for error in serializer.errors[field]] == [error_code]

    def test_auth_types_without_kinds_raises(self) -> None:
        with self.assertRaises(ValueError):
            IntegrationReferenceField(auth_types="any")

    def test_reads_the_team_from_get_team(self) -> None:
        serializer = self._validate({"integration": self.slack.id}, context={"get_team": lambda: self.team})

        assert serializer.validated_data == {"integration": self.slack}

    @parameterized.expand(
        [
            ("other_team", lambda self: {"integration": self.other.id}, "integration", "does_not_exist"),
            ("missing", lambda self: {"integration": 10**9}, "integration", "does_not_exist"),
            (
                "other_kind",
                lambda self: {"integration": self.slack.id, "github": self.slack.id},
                "github",
                "does_not_exist",
            ),
            # The field reads only named rows, so a warehouse source row does not exist for it.
            (
                "source_row_without_kinds",
                lambda self: {"integration": self.github_source_row.id},
                "integration",
                "does_not_exist",
            ),
            (
                "source_row_of_the_kind",
                lambda self: {"integration": self.slack.id, "github": self.github_source_row.id},
                "github",
                "does_not_exist",
            ),
            ("not_a_number", lambda self: {"integration": "abc"}, "integration", "incorrect_type"),
            ("bool", lambda self: {"integration": True}, "integration", "incorrect_type"),
            ("list", lambda self: {"integration": [1]}, "integration", "incorrect_type"),
        ]
    )
    def test_rejects(self, _name: str, data: Any, field: str, code: str) -> None:
        serializer = self._validate(data(self))

        assert [error.code for error in serializer.errors[field]] == [code]

    def test_needs_a_team_in_the_context(self) -> None:
        serializer = self._validate({"integration": self.slack.id}, context={})

        assert [error.code for error in serializer.errors["integration"]] == ["no_team"]

    def test_represents_the_id(self) -> None:
        field = IntegrationReferenceField()

        assert (field.to_representation(self.slack), field.to_representation(self.slack.id)) == (
            self.slack.id,
            self.slack.id,
        )


class _ReadSerializer(serializers.Serializer):
    integration = IntegrationReferenceField(allow_null=True)


class _Holder:
    def __init__(self, integration: Integration | None) -> None:
        self.integration = integration


class TestIntegrationReferenceFieldRead(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.slack = Integration.objects._with_auth(ANY).create(team=self.team, kind="slack", integration_id="s")

    def test_reads_the_foreign_key_column_without_a_query(self) -> None:
        thread = CommentSlackThread(team=self.team, integration_id=self.slack.id)

        with self.assertNumQueries(0):
            data = _ReadSerializer(thread).data

        assert data == {"integration": self.slack.id}

    @parameterized.expand(
        [
            ("model_field_null", lambda self: CommentSlackThread(team=self.team, integration_id=None), None),
            ("plain_attribute", lambda self: _Holder(self.slack), "slack"),
            ("plain_attribute_null", lambda self: _Holder(None), None),
        ]
    )
    def test_represents(self, _name: str, build: Any, expected: str | None) -> None:
        data = _ReadSerializer(build(self)).data

        assert data == {"integration": None if expected is None else getattr(self, expected).id}
