from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.feature_flag.flag_matching import (
    WRITE_DATABASE_FOR_PERSONS,
    _get_existing_hash_key_override_flag_keys,
    _get_feature_flag_hash_key_overrides_via_personhog,
    get_feature_flag_hash_key_overrides,
    set_feature_flag_hash_key_overrides,
)
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.proto.generated.personhog.types.v1 import feature_flag_pb2

_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"
_ROUTING_TOTAL_PATCH = "posthog.personhog_client.metrics.PERSONHOG_ROUTING_TOTAL"
_ROUTING_ERRORS_PATCH = "posthog.personhog_client.metrics.PERSONHOG_ROUTING_ERRORS_TOTAL"


# ── get_feature_flag_hash_key_overrides ──────────────────────────────


class TestGetFeatureFlagHashKeyOverridesRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("client_is_none_falls_back_to_orm", None, None, "django_orm"),
            ("client_raises_falls_back_to_orm", MagicMock, RuntimeError("grpc error"), "django_orm"),
            ("client_succeeds_returns_personhog_result", MagicMock, None, "personhog"),
        ]
    )
    @patch("posthog.models.feature_flag.flag_matching.PersonDistinctId")
    @patch("posthog.models.feature_flag.flag_matching.FeatureFlagHashKeyOverride")
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_routing(
        self,
        _name,
        client_factory,
        grpc_exception,
        expected_source,
        mock_get_client,
        mock_routing_total,
        mock_routing_errors,
        mock_override_objects,
        mock_pdi_objects,
    ):
        if client_factory is None:
            mock_get_client.return_value = None
        else:
            mock_client = MagicMock()
            if grpc_exception is not None:
                mock_client.get_hash_key_override_context.side_effect = grpc_exception
            else:
                mock_client.get_hash_key_override_context.return_value = (
                    feature_flag_pb2.GetHashKeyOverrideContextResponse(
                        results=[
                            feature_flag_pb2.HashKeyOverrideContext(
                                person_id=1,
                                distinct_id="did-1",
                                overrides=[feature_flag_pb2.HashKeyOverride(feature_flag_key="flag-a", hash_key="abc")],
                            )
                        ]
                    )
                )
            mock_get_client.return_value = mock_client

        mock_pdi_qs = MagicMock()
        mock_pdi_qs.values_list.return_value = []
        mock_pdi_objects.objects.db_manager.return_value.filter.return_value = mock_pdi_qs

        mock_override_qs = MagicMock()
        mock_override_qs.db_manager.return_value.filter.return_value.values_list.return_value = []
        mock_override_objects.objects = mock_override_qs

        result = get_feature_flag_hash_key_overrides(team_id=1, distinct_ids=["did-1"])

        assert isinstance(result, dict)

        mock_routing_total.labels.assert_called_with(
            operation="get_feature_flag_hash_key_overrides",
            source=expected_source,
            client_name="posthog-django",
        )
        mock_routing_total.labels.return_value.inc.assert_called()

        if grpc_exception is not None:
            mock_routing_errors.labels.assert_called_once_with(
                operation="get_feature_flag_hash_key_overrides",
                source="personhog",
                error_type="grpc_error",
                client_name="posthog-django",
            )
            mock_routing_errors.labels.return_value.inc.assert_called_once()
        else:
            mock_routing_errors.labels.assert_not_called()

    @patch("posthog.models.feature_flag.flag_matching.PersonDistinctId")
    @patch("posthog.models.feature_flag.flag_matching.FeatureFlagHashKeyOverride")
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_result_returned_directly(
        self,
        mock_get_client,
        mock_routing_total,
        mock_routing_errors,
        mock_override_objects,
        mock_pdi_objects,
    ):
        mock_client = MagicMock()
        mock_client.get_hash_key_override_context.return_value = feature_flag_pb2.GetHashKeyOverrideContextResponse(
            results=[
                feature_flag_pb2.HashKeyOverrideContext(
                    person_id=1,
                    distinct_id="did-1",
                    overrides=[feature_flag_pb2.HashKeyOverride(feature_flag_key="flag-a", hash_key="hash-xyz")],
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = get_feature_flag_hash_key_overrides(team_id=1, distinct_ids=["did-1"])

        assert result == {"flag-a": "hash-xyz"}
        mock_pdi_objects.objects.db_manager.assert_not_called()


class TestGetFeatureFlagHashKeyOverridesViaPersonhog(SimpleTestCase):
    def test_returns_overrides_from_personhog(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="hash-aaa", distinct_id="did-1"
            )

            result = _get_feature_flag_hash_key_overrides_via_personhog(
                team_id=1, distinct_ids=["did-1"], using_database=WRITE_DATABASE_FOR_PERSONS
            )

        assert result == {"flag-a": "hash-aaa"}

    def test_returns_empty_dict_when_no_overrides(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])

            result = _get_feature_flag_hash_key_overrides_via_personhog(
                team_id=1, distinct_ids=["did-1"], using_database=WRITE_DATABASE_FOR_PERSONS
            )

        assert result == {}

    def test_returns_empty_dict_when_no_persons(self):
        with fake_personhog_client():
            result = _get_feature_flag_hash_key_overrides_via_personhog(
                team_id=1, distinct_ids=["nonexistent"], using_database=WRITE_DATABASE_FOR_PERSONS
            )

        assert result == {}

    def test_raises_when_client_is_none(self):
        with patch(_CLIENT_PATCH, return_value=None):
            with self.assertRaises(RuntimeError, msg="personhog client not configured"):
                _get_feature_flag_hash_key_overrides_via_personhog(
                    team_id=1, distinct_ids=["did-1"], using_database=WRITE_DATABASE_FOR_PERSONS
                )

    @patch(_CLIENT_PATCH)
    def test_write_database_uses_strong_consistency(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_hash_key_override_context.return_value = feature_flag_pb2.GetHashKeyOverrideContextResponse(
            results=[]
        )
        mock_get_client.return_value = mock_client

        _get_feature_flag_hash_key_overrides_via_personhog(
            team_id=1, distinct_ids=["did-1"], using_database=WRITE_DATABASE_FOR_PERSONS
        )

        mock_client.get_hash_key_override_context.assert_called_once()
        req = mock_client.get_hash_key_override_context.call_args[0][0]
        assert req.HasField("read_options"), "expected read_options to be set for WRITE_DATABASE_FOR_PERSONS"
        from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG

        assert req.read_options.consistency == CONSISTENCY_LEVEL_STRONG

    @patch(_CLIENT_PATCH)
    def test_non_write_database_skips_strong_consistency(self, mock_get_client):
        # Use an explicit non-write database alias to verify the no-strong-consistency path.
        # In test/dev mode both PERSONS_DB constants resolve to the same value ("persons_db_writer"),
        # so we pass an explicit alias that differs from WRITE_DATABASE_FOR_PERSONS.
        non_write_alias = "persons_db_reader"
        mock_client = MagicMock()
        mock_client.get_hash_key_override_context.return_value = feature_flag_pb2.GetHashKeyOverrideContextResponse(
            results=[]
        )
        mock_get_client.return_value = mock_client

        _get_feature_flag_hash_key_overrides_via_personhog(
            team_id=1, distinct_ids=["did-1"], using_database=non_write_alias
        )

        mock_client.get_hash_key_override_context.assert_called_once()
        req = mock_client.get_hash_key_override_context.call_args[0][0]
        assert not req.HasField("read_options"), "expected no read_options when using a non-write database alias"

    def test_first_distinct_id_person_overrides_win(self):
        with fake_personhog_client() as fake:
            # Person 10 maps to did-1 (first in list) — their override should win
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="hash-from-first", distinct_id="did-1"
            )
            # Person 20 maps to did-2 — their override for flag-a should lose
            fake.add_person(team_id=1, person_id=20, uuid="uuid-20", distinct_ids=["did-2"])
            fake.add_hash_key_override(
                team_id=1, person_id=20, feature_flag_key="flag-a", hash_key="hash-from-second", distinct_id="did-2"
            )

            result = _get_feature_flag_hash_key_overrides_via_personhog(
                team_id=1, distinct_ids=["did-1", "did-2"], using_database=WRITE_DATABASE_FOR_PERSONS
            )

        assert result["flag-a"] == "hash-from-first"

    def test_multiple_flags_merged_across_persons(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="hash-a", distinct_id="did-1"
            )
            fake.add_person(team_id=1, person_id=20, uuid="uuid-20", distinct_ids=["did-2"])
            fake.add_hash_key_override(
                team_id=1, person_id=20, feature_flag_key="flag-b", hash_key="hash-b", distinct_id="did-2"
            )

            result = _get_feature_flag_hash_key_overrides_via_personhog(
                team_id=1, distinct_ids=["did-1", "did-2"], using_database=WRITE_DATABASE_FOR_PERSONS
            )

        assert result == {"flag-a": "hash-a", "flag-b": "hash-b"}


# ── _get_existing_hash_key_override_flag_keys ────────────────────────


class TestGetExistingHashKeyOverrideFlagKeysRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("client_is_none_falls_back_to_orm", None, None, "django_orm"),
            ("client_raises_falls_back_to_orm", MagicMock, RuntimeError("grpc error"), "django_orm"),
            ("client_succeeds_records_personhog", MagicMock, None, "personhog"),
        ]
    )
    @patch("posthog.models.feature_flag.flag_matching.execute_with_timeout")
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_routing(
        self,
        _name,
        client_factory,
        grpc_exception,
        expected_source,
        mock_get_client,
        mock_routing_total,
        mock_routing_errors,
        mock_execute_with_timeout,
    ):
        if client_factory is None:
            mock_get_client.return_value = None
        else:
            mock_client = MagicMock()
            if grpc_exception is not None:
                mock_client.get_hash_key_override_context.side_effect = grpc_exception
            else:
                mock_client.get_hash_key_override_context.return_value = (
                    feature_flag_pb2.GetHashKeyOverrideContextResponse(
                        results=[
                            feature_flag_pb2.HashKeyOverrideContext(
                                person_id=1,
                                distinct_id="did-1",
                                overrides=[],
                                existing_feature_flag_keys=["flag-x"],
                            )
                        ]
                    )
                )
            mock_get_client.return_value = mock_client

        # ORM path uses execute_with_timeout as context manager returning a cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1,)]
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_cursor)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_execute_with_timeout.return_value = mock_context

        _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["did-1"])

        mock_routing_total.labels.assert_called_with(
            operation="get_existing_hash_key_override_flag_keys",
            source=expected_source,
            client_name="posthog-django",
        )
        mock_routing_total.labels.return_value.inc.assert_called()

        if grpc_exception is not None:
            mock_routing_errors.labels.assert_called_once_with(
                operation="get_existing_hash_key_override_flag_keys",
                source="personhog",
                error_type="grpc_error",
                client_name="posthog-django",
            )
            mock_routing_errors.labels.return_value.inc.assert_called_once()
        else:
            mock_routing_errors.labels.assert_not_called()

    @patch("posthog.models.feature_flag.flag_matching.execute_with_timeout")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_returns_none_when_personhog_finds_no_persons(
        self, mock_get_client, mock_routing_total, mock_execute_with_timeout
    ):
        mock_client = MagicMock()
        mock_client.get_hash_key_override_context.return_value = feature_flag_pb2.GetHashKeyOverrideContextResponse(
            results=[]
        )
        mock_get_client.return_value = mock_client

        result = _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["unknown-did"])

        assert result is None
        mock_execute_with_timeout.assert_not_called()

    @patch("posthog.models.feature_flag.flag_matching.execute_with_timeout")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_returns_set_of_existing_flag_keys(self, mock_get_client, mock_routing_total, mock_execute_with_timeout):
        mock_client = MagicMock()
        mock_client.get_hash_key_override_context.return_value = feature_flag_pb2.GetHashKeyOverrideContextResponse(
            results=[
                feature_flag_pb2.HashKeyOverrideContext(
                    person_id=1,
                    distinct_id="did-1",
                    overrides=[],
                    existing_feature_flag_keys=["flag-a", "flag-b"],
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["did-1"])

        assert result == {"flag-a", "flag-b"}
        mock_execute_with_timeout.assert_not_called()

    @patch("posthog.models.feature_flag.flag_matching.execute_with_timeout")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_merges_existing_keys_from_multiple_persons(
        self, mock_get_client, mock_routing_total, mock_execute_with_timeout
    ):
        mock_client = MagicMock()
        mock_client.get_hash_key_override_context.return_value = feature_flag_pb2.GetHashKeyOverrideContextResponse(
            results=[
                feature_flag_pb2.HashKeyOverrideContext(
                    person_id=1,
                    distinct_id="did-1",
                    overrides=[],
                    existing_feature_flag_keys=["flag-a"],
                ),
                feature_flag_pb2.HashKeyOverrideContext(
                    person_id=2,
                    distinct_id="did-2",
                    overrides=[],
                    existing_feature_flag_keys=["flag-b", "flag-c"],
                ),
            ]
        )
        mock_get_client.return_value = mock_client

        result = _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["did-1", "did-2"])

        assert result == {"flag-a", "flag-b", "flag-c"}


class TestGetExistingHashKeyOverrideFlagKeysViaFakeClient(SimpleTestCase):
    def test_returns_none_when_no_persons_exist(self):
        with fake_personhog_client():
            result = _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["nonexistent"])

        assert result is None

    def test_returns_empty_set_when_person_exists_but_no_overrides(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])

            result = _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["did-1"])

        assert result == set()

    def test_returns_flag_keys_with_overrides(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="any", distinct_id="did-1"
            )
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-b", hash_key="any2", distinct_id="did-1"
            )

            result = _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["did-1"])

        assert result == {"flag-a", "flag-b"}

    def test_check_person_exists_request_sent(self):
        with fake_personhog_client() as fake:
            _get_existing_hash_key_override_flag_keys(team_id=1, distinct_ids=["did-1"])

            calls = fake.assert_called("get_hash_key_override_context")
            assert calls[0].request.check_person_exists is True


# ── set_feature_flag_hash_key_overrides ──────────────────────────────


class TestSetFeatureFlagHashKeyOverridesRouting(SimpleTestCase):
    def _make_team(self, team_id: int = 1, project_id: int = 100) -> MagicMock:
        team = MagicMock()
        team.id = team_id
        team.project_id = project_id
        return team

    @parameterized.expand(
        [
            ("client_is_none_falls_back_to_orm", None, None, "django_orm"),
            ("client_raises_falls_back_to_orm", MagicMock, RuntimeError("grpc error"), "django_orm"),
            ("client_succeeds_records_personhog", MagicMock, None, "personhog"),
        ]
    )
    @patch("posthog.models.feature_flag.flag_matching.execute_with_timeout")
    @patch("posthog.models.feature_flag.flag_matching._get_experience_continuity_flag_keys")
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_routing(
        self,
        _name,
        client_factory,
        grpc_exception,
        expected_source,
        mock_get_client,
        mock_routing_total,
        mock_routing_errors,
        mock_get_flags,
        mock_execute_with_timeout,
    ):
        mock_get_flags.return_value = {"flag-a"}

        if client_factory is None:
            mock_get_client.return_value = None
        else:
            mock_client = MagicMock()
            if grpc_exception is not None:
                mock_client.upsert_hash_key_overrides.side_effect = grpc_exception
            else:
                mock_client.upsert_hash_key_overrides.return_value = feature_flag_pb2.UpsertHashKeyOverridesResponse(
                    inserted_count=1
                )
            mock_get_client.return_value = mock_client

        # ORM path cursor setup
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [[(10,)], []]  # person_ids then existing overrides
        mock_cursor.rowcount = 1
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_cursor)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_execute_with_timeout.return_value = mock_context

        team = self._make_team()
        set_feature_flag_hash_key_overrides(team=team, distinct_ids=["did-1"], hash_key_override="hash-new")

        mock_routing_total.labels.assert_called_with(
            operation="set_feature_flag_hash_key_overrides",
            source=expected_source,
            client_name="posthog-django",
        )
        mock_routing_total.labels.return_value.inc.assert_called()

        if grpc_exception is not None:
            mock_routing_errors.labels.assert_called_once_with(
                operation="set_feature_flag_hash_key_overrides",
                source="personhog",
                error_type="grpc_error",
                client_name="posthog-django",
            )
            mock_routing_errors.labels.return_value.inc.assert_called_once()
        else:
            mock_routing_errors.labels.assert_not_called()

    @patch("posthog.models.feature_flag.flag_matching._get_experience_continuity_flag_keys")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_returns_false_when_no_experience_continuity_flags(
        self, mock_get_client, mock_routing_total, mock_get_flags
    ):
        mock_get_client.return_value = MagicMock()
        mock_get_flags.return_value = set()

        team = self._make_team()
        result = set_feature_flag_hash_key_overrides(team=team, distinct_ids=["did-1"], hash_key_override="hash-new")

        assert result is False

    @patch("posthog.models.feature_flag.flag_matching._get_experience_continuity_flag_keys")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_returns_true_when_overrides_inserted(self, mock_get_client, mock_routing_total, mock_get_flags):
        mock_get_flags.return_value = {"flag-a"}
        mock_client = MagicMock()
        mock_client.upsert_hash_key_overrides.return_value = feature_flag_pb2.UpsertHashKeyOverridesResponse(
            inserted_count=3
        )
        mock_get_client.return_value = mock_client

        team = self._make_team()
        result = set_feature_flag_hash_key_overrides(team=team, distinct_ids=["did-1"], hash_key_override="hash-new")

        assert result is True

    @patch("posthog.models.feature_flag.flag_matching._get_experience_continuity_flag_keys")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_returns_false_when_zero_overrides_inserted(self, mock_get_client, mock_routing_total, mock_get_flags):
        mock_get_flags.return_value = {"flag-a"}
        mock_client = MagicMock()
        mock_client.upsert_hash_key_overrides.return_value = feature_flag_pb2.UpsertHashKeyOverridesResponse(
            inserted_count=0
        )
        mock_get_client.return_value = mock_client

        team = self._make_team()
        result = set_feature_flag_hash_key_overrides(team=team, distinct_ids=["did-1"], hash_key_override="hash-new")

        assert result is False

    @patch("posthog.models.feature_flag.flag_matching._get_experience_continuity_flag_keys")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_upsert_request_uses_team_and_flag_keys(self, mock_get_client, mock_routing_total, mock_get_flags):
        mock_get_flags.return_value = {"flag-a", "flag-b"}
        mock_client = MagicMock()
        mock_client.upsert_hash_key_overrides.return_value = feature_flag_pb2.UpsertHashKeyOverridesResponse(
            inserted_count=2
        )
        mock_get_client.return_value = mock_client

        team = self._make_team(team_id=42, project_id=100)
        set_feature_flag_hash_key_overrides(team=team, distinct_ids=["did-1", "did-2"], hash_key_override="my-hash")

        mock_client.upsert_hash_key_overrides.assert_called_once()
        req = mock_client.upsert_hash_key_overrides.call_args[0][0]
        assert req.team_id == 42
        assert req.hash_key == "my-hash"
        assert set(req.distinct_ids) == {"did-1", "did-2"}
        assert set(req.feature_flag_keys) == {"flag-a", "flag-b"}


class TestSetFeatureFlagHashKeyOverridesViaFakeClient(SimpleTestCase):
    def _make_team(self, team_id: int = 1, project_id: int = 100) -> MagicMock:
        team = MagicMock()
        team.id = team_id
        team.project_id = project_id
        return team

    @patch("posthog.models.feature_flag.flag_matching._get_experience_continuity_flag_keys")
    def test_inserts_overrides_for_known_persons(self, mock_get_flags):
        mock_get_flags.return_value = {"flag-a"}

        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])

            team = self._make_team()
            result = set_feature_flag_hash_key_overrides(
                team=team, distinct_ids=["did-1"], hash_key_override="hash-xyz"
            )

            assert result is True
            fake.assert_called("upsert_hash_key_overrides")

    @patch("posthog.models.feature_flag.flag_matching._get_experience_continuity_flag_keys")
    def test_returns_false_when_no_persons_found(self, mock_get_flags):
        mock_get_flags.return_value = {"flag-a"}

        with fake_personhog_client():
            team = self._make_team()
            result = set_feature_flag_hash_key_overrides(
                team=team, distinct_ids=["no-such-person"], hash_key_override="hash-xyz"
            )

            # upsert is still called (server returns 0 inserted because no persons resolve)
            assert result is False


# ── Fake client unit tests ───────────────────────────────────────────


class TestFakeClientHashKeyOverrides(SimpleTestCase):
    def test_get_context_returns_overrides_for_known_distinct_id(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="hash-abc", distinct_id="did-1"
            )

            resp = fake.get_hash_key_override_context(
                feature_flag_pb2.GetHashKeyOverrideContextRequest(team_id=1, distinct_ids=["did-1"])
            )

        assert len(resp.results) == 1
        ctx = resp.results[0]
        assert ctx.person_id == 10
        assert ctx.distinct_id == "did-1"
        assert len(ctx.overrides) == 1
        assert ctx.overrides[0].feature_flag_key == "flag-a"
        assert ctx.overrides[0].hash_key == "hash-abc"
        assert "flag-a" in ctx.existing_feature_flag_keys

    def test_get_context_returns_empty_when_no_persons(self):
        with fake_personhog_client() as fake:
            resp = fake.get_hash_key_override_context(
                feature_flag_pb2.GetHashKeyOverrideContextRequest(team_id=1, distinct_ids=["unknown"])
            )

        assert resp.results == []

    def test_get_context_check_person_exists_returns_empty_when_no_persons(self):
        with fake_personhog_client() as fake:
            resp = fake.get_hash_key_override_context(
                feature_flag_pb2.GetHashKeyOverrideContextRequest(
                    team_id=1, distinct_ids=["unknown"], check_person_exists=True
                )
            )

        assert resp.results == []

    def test_get_context_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=999, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])
            fake.add_hash_key_override(
                team_id=999, person_id=10, feature_flag_key="flag-a", hash_key="hash-abc", distinct_id="did-1"
            )

            resp = fake.get_hash_key_override_context(
                feature_flag_pb2.GetHashKeyOverrideContextRequest(team_id=1, distinct_ids=["did-1"])
            )

        assert resp.results == []

    def test_upsert_inserts_new_overrides(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])

            resp = fake.upsert_hash_key_overrides(
                feature_flag_pb2.UpsertHashKeyOverridesRequest(
                    team_id=1,
                    distinct_ids=["did-1"],
                    hash_key="new-hash",
                    feature_flag_keys=["flag-a", "flag-b"],
                )
            )

        assert resp.inserted_count == 2
        assert fake._hash_key_overrides[(1, 10, "flag-a")] == "new-hash"
        assert fake._hash_key_overrides[(1, 10, "flag-b")] == "new-hash"

    def test_upsert_skips_existing_overrides(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid="uuid-10", distinct_ids=["did-1"])
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="original", distinct_id="did-1"
            )

            resp = fake.upsert_hash_key_overrides(
                feature_flag_pb2.UpsertHashKeyOverridesRequest(
                    team_id=1,
                    distinct_ids=["did-1"],
                    hash_key="new-hash",
                    feature_flag_keys=["flag-a"],
                )
            )

        assert resp.inserted_count == 0
        # Original hash preserved
        assert fake._hash_key_overrides[(1, 10, "flag-a")] == "original"

    def test_upsert_returns_zero_when_no_persons(self):
        with fake_personhog_client() as fake:
            resp = fake.upsert_hash_key_overrides(
                feature_flag_pb2.UpsertHashKeyOverridesRequest(
                    team_id=1,
                    distinct_ids=["no-such-person"],
                    hash_key="new-hash",
                    feature_flag_keys=["flag-a"],
                )
            )

        assert resp.inserted_count == 0

    def test_delete_by_teams_removes_overrides(self):
        with fake_personhog_client() as fake:
            fake.add_hash_key_override(team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="h1")
            fake.add_hash_key_override(team_id=2, person_id=20, feature_flag_key="flag-b", hash_key="h2")

            resp = fake.delete_hash_key_overrides_by_teams(
                feature_flag_pb2.DeleteHashKeyOverridesByTeamsRequest(team_ids=[1])
            )

        assert resp.deleted_count == 1
        assert (1, 10, "flag-a") not in fake._hash_key_overrides
        assert (2, 20, "flag-b") in fake._hash_key_overrides

    def test_delete_by_teams_removes_person_lookup_entries(self):
        with fake_personhog_client() as fake:
            fake.add_hash_key_override(
                team_id=1, person_id=10, feature_flag_key="flag-a", hash_key="h1", distinct_id="did-1"
            )

            fake.delete_hash_key_overrides_by_teams(feature_flag_pb2.DeleteHashKeyOverridesByTeamsRequest(team_ids=[1]))

        assert (1, "did-1") not in fake._hash_key_person_lookup
