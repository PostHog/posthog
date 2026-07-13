from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.models.person.util import (
    _fetch_person_by_distinct_id_via_personhog,
    _fetch_person_by_id_via_personhog,
    _fetch_person_by_uuid_via_personhog,
    _fetch_persons_by_distinct_ids_via_personhog,
    _fetch_persons_by_uuids_via_personhog,
    _validate_uuids_via_personhog,
    get_person_by_pk_or_uuid,
    get_person_ids_and_uuids_by_uuids,
    get_person_uuids_by_distinct_ids,
    get_persons_mapped_by_distinct_id,
)
from posthog.personhog_client.client import personhog_call
from posthog.personhog_client.fake_client import fake_personhog_client, get_active_fake
from posthog.personhog_client.test_helpers import PersonhogTestMixin
from posthog.test.persons import create_person

# ── Personhog internal logic tests ──────────────────────────────────
# These use the fake personhog client to exercise the real proto/converter pipeline.


class TestFetchPersonByUuidViaPersonhog(SimpleTestCase):
    def test_returns_person_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "test@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_person_by_uuid_via_personhog(team_id=1, uuid="550e8400-e29b-41d4-a716-446655440000")

            assert result is not None
            assert result.id == 42
            assert result.properties == {"email": "test@example.com"}
            assert result.distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_person_by_uuid")
            fake.assert_called("get_distinct_ids_for_person")

    def test_returns_none_when_person_not_found(self):
        with fake_personhog_client() as fake:
            result = _fetch_person_by_uuid_via_personhog(team_id=1, uuid="nonexistent")

            assert result is None
            fake.assert_called("get_person_by_uuid")
            fake.assert_not_called("get_distinct_ids_for_person")

    def test_returns_none_on_team_mismatch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["did-1"],
            )

            result = _fetch_person_by_uuid_via_personhog(team_id=1, uuid="550e8400-e29b-41d4-a716-446655440000")

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")


class TestFetchPersonByDistinctIdViaPersonhog(SimpleTestCase):
    def test_returns_person_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "test@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_person_by_distinct_id_via_personhog(team_id=1, distinct_id="did-1")

            assert result is not None
            assert result.id == 42
            assert result.distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_person_by_distinct_id")

    def test_returns_none_when_person_not_found(self):
        with fake_personhog_client() as fake:
            result = _fetch_person_by_distinct_id_via_personhog(team_id=1, distinct_id="nonexistent")

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")

    def test_returns_none_on_team_mismatch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["did-1"],
            )

            result = _fetch_person_by_distinct_id_via_personhog(team_id=1, distinct_id="did-1")

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")


class TestFetchPersonByIdViaPersonhog(SimpleTestCase):
    def test_returns_person_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "test@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_person_by_id_via_personhog(team_id=1, person_id=42)

            assert result is not None
            assert result.id == 42
            assert result.properties == {"email": "test@example.com"}
            assert result.distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_person")
            fake.assert_called("get_distinct_ids_for_person")

    def test_returns_none_when_person_not_found(self):
        with fake_personhog_client() as fake:
            result = _fetch_person_by_id_via_personhog(team_id=1, person_id=999)

            assert result is None
            fake.assert_called("get_person")
            fake.assert_not_called("get_distinct_ids_for_person")

    def test_returns_none_on_team_mismatch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["did-1"],
            )

            result = _fetch_person_by_id_via_personhog(team_id=1, person_id=42)

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")


class TestFetchPersonsByDistinctIdsViaPersonhog(SimpleTestCase):
    def test_returns_persons_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "real@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["did-1"])

            assert len(result) == 1
            assert result[0].id == 42
            assert result[0].properties == {"email": "real@example.com"}
            assert result[0].distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_persons_by_distinct_ids_in_team")
            fake.assert_called("get_distinct_ids_for_persons")

    def test_no_results_for_missing_distinct_ids(self):
        with fake_personhog_client() as fake:
            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["nonexistent"])

            assert result == []
            fake.assert_called("get_persons_by_distinct_ids_in_team")
            fake.assert_not_called("get_distinct_ids_for_persons")

    def test_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1"]
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["did-1"])

            assert result == []

    def test_deduplicates_persons_with_multiple_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1", "did-2"]
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["did-1", "did-2"])

            assert len(result) == 1

    def test_respects_distinct_id_limit(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440042",
                distinct_ids=["did-1", "did-2", "did-3"],
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(
                team_id=1, distinct_ids=["did-1"], distinct_id_limit=1
            )

            assert len(result) == 1
            assert len(result[0].distinct_ids) == 1


class TestFetchPersonsByUuidsViaPersonhog(SimpleTestCase):
    def test_returns_persons_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=1,
                uuid="550e8400-e29b-41d4-a716-446655440001",
                properties={"name": "Alice"},
                distinct_ids=["alice-did"],
            )
            fake.add_person(
                team_id=1,
                person_id=2,
                uuid="550e8400-e29b-41d4-a716-446655440002",
                properties={"name": "Bob"},
                distinct_ids=["bob-did"],
            )

            result = _fetch_persons_by_uuids_via_personhog(
                team_id=1,
                uuids=["550e8400-e29b-41d4-a716-446655440001", "550e8400-e29b-41d4-a716-446655440002"],
            )

            assert len(result) == 2
            assert result[0].properties == {"name": "Alice"}
            assert result[0].distinct_ids == ["alice-did"]
            assert result[1].properties == {"name": "Bob"}
            assert result[1].distinct_ids == ["bob-did"]
            fake.assert_called("get_persons_by_uuids")
            fake.assert_called("get_distinct_ids_for_persons")

    def test_returns_empty_for_missing_uuids(self):
        with fake_personhog_client() as fake:
            result = _fetch_persons_by_uuids_via_personhog(team_id=1, uuids=["nonexistent"])

            assert result == []
            fake.assert_called("get_persons_by_uuids")
            fake.assert_not_called("get_distinct_ids_for_persons")

    def test_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1"]
            )

            result = _fetch_persons_by_uuids_via_personhog(team_id=1, uuids=["550e8400-e29b-41d4-a716-446655440042"])

            assert result == []

    def test_person_with_no_distinct_ids_gets_empty_list(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042")

            result = _fetch_persons_by_uuids_via_personhog(team_id=1, uuids=["550e8400-e29b-41d4-a716-446655440042"])

            assert len(result) == 1
            assert result[0].distinct_ids == []

    def test_distinct_id_limit_zero_skips_fetch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["d1", "d2", "d3"]
            )

            result = _fetch_persons_by_uuids_via_personhog(
                team_id=1, uuids=["550e8400-e29b-41d4-a716-446655440042"], distinct_id_limit=0
            )

            assert len(result) == 1
            assert result[0].distinct_ids == []
            fake.assert_called("get_persons_by_uuids")
            fake.assert_not_called("get_distinct_ids_for_persons")

    def test_distinct_id_limit_bounds_fetch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["d1", "d2", "d3"]
            )

            result = _fetch_persons_by_uuids_via_personhog(
                team_id=1, uuids=["550e8400-e29b-41d4-a716-446655440042"], distinct_id_limit=2
            )

            assert result[0].distinct_ids == ["d1", "d2"]


class TestValidateUuidsViaPersonhog(SimpleTestCase):
    def test_returns_matching_uuids(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
            fake.add_person(team_id=1, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

            result = _validate_uuids_via_personhog(team_id=1, uuids=["uuid-1", "uuid-2", "uuid-missing"])

            assert set(result) == {"uuid-1", "uuid-2"}
            fake.assert_called("get_persons_by_uuids")

    def test_filters_out_wrong_team(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
            fake.add_person(team_id=999, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

            result = _validate_uuids_via_personhog(team_id=1, uuids=["uuid-1", "uuid-2"])

            assert result == ["uuid-1"]

    def test_returns_empty_when_no_matches(self):
        with fake_personhog_client() as fake:
            result = _validate_uuids_via_personhog(team_id=1, uuids=["nonexistent"])

            assert result == []
            fake.assert_called("get_persons_by_uuids")

    def test_sends_uuid_only_field_mask(self):
        # Existence checks must never pull full person rows — the mask keeps (potentially
        # huge) person properties out of the RPC payloads.
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

            _validate_uuids_via_personhog(team_id=1, uuids=["uuid-1"])

            calls = fake.assert_called("get_persons_by_uuids", times=1)
            mask = list(calls[0].request.read_options.field_mask)
            assert "uuid" in mask
            assert "id" in mask
            assert "team_id" in mask
            assert "properties" not in mask


class TestGetPersonIdsAndUuidsByUuids(SimpleTestCase):
    def test_returns_pairs_for_matching_uuids_and_skips_missing(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
            fake.add_person(team_id=1, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

            result = get_person_ids_and_uuids_by_uuids(1, ["uuid-1", "uuid-2", "uuid-missing"])

            assert result == [(1, "uuid-1"), (2, "uuid-2")]
            fake.assert_not_called("get_distinct_ids_for_persons")

    def test_returns_empty_list_for_empty_input(self):
        with fake_personhog_client() as fake:
            assert get_person_ids_and_uuids_by_uuids(1, []) == []
            fake.assert_not_called("get_persons_by_uuids")

    def test_sends_uuid_only_field_mask(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

            get_person_ids_and_uuids_by_uuids(1, ["uuid-1"])

            calls = fake.assert_called("get_persons_by_uuids", times=1)
            mask = list(calls[0].request.read_options.field_mask)
            assert "uuid" in mask
            assert "id" in mask
            assert "team_id" in mask
            assert "properties" not in mask


# ── Delegation tests ────────────────────────────────────────────────


class TestGetPersonByPkOrUuid(SimpleTestCase):
    @patch("posthog.models.person.util.get_person_by_uuid")
    def test_routes_uuid_key_to_get_person_by_uuid(self, mock_get_by_uuid):
        mock_person = MagicMock()
        mock_get_by_uuid.return_value = mock_person

        result = get_person_by_pk_or_uuid(1, "550e8400-e29b-41d4-a716-446655440000")

        assert result == mock_person
        mock_get_by_uuid.assert_called_once_with(1, "550e8400-e29b-41d4-a716-446655440000", distinct_id_limit=None)

    @patch("posthog.models.person.util.get_person_by_id")
    def test_routes_int_key_to_get_person_by_id(self, mock_get_by_id):
        mock_person = MagicMock()
        mock_get_by_id.return_value = mock_person

        result = get_person_by_pk_or_uuid(1, "42")

        assert result == mock_person
        mock_get_by_id.assert_called_once_with(1, 42, distinct_id_limit=None)

    def test_returns_none_for_invalid_key(self):
        result = get_person_by_pk_or_uuid(1, "not-a-uuid-or-int")

        assert result is None

    @patch("posthog.models.person.util.get_person_by_uuid")
    def test_returns_none_when_uuid_lookup_finds_nothing(self, mock_get_by_uuid):
        mock_get_by_uuid.return_value = None

        result = get_person_by_pk_or_uuid(1, "550e8400-e29b-41d4-a716-446655440000")

        assert result is None

    @patch("posthog.models.person.util.get_person_by_id")
    def test_returns_none_when_id_lookup_finds_nothing(self, mock_get_by_id):
        mock_get_by_id.return_value = None

        result = get_person_by_pk_or_uuid(1, "42")

        assert result is None


# ── personhog_call unit tests ────────────────────────────────────


class TestPersonhogCall(SimpleTestCase):
    @patch("posthog.personhog_client.metrics.PERSONHOG_ROUTING_TOTAL")
    def test_calls_fn_and_increments_counter(self, mock_routing):
        result = personhog_call("test_op", lambda: "personhog_result")

        assert result == "personhog_result"
        mock_routing.labels.assert_called_with(operation="test_op", source="personhog", client_name="posthog-django")
        mock_routing.labels.return_value.inc.assert_called_once()

    @patch("posthog.personhog_client.metrics.PERSONHOG_ROUTING_TOTAL")
    def test_exception_propagates(self, mock_routing):
        def failing_fn():
            raise RuntimeError("grpc timeout")

        with self.assertRaises(RuntimeError):
            personhog_call("test_op", failing_fn)

    @patch("posthog.personhog_client.metrics.PERSONHOG_ROUTING_TOTAL")
    def test_returning_none_is_not_treated_as_failure(self, mock_routing):
        result = personhog_call("test_op", lambda: None)

        assert result is None
        mock_routing.labels.assert_called_with(operation="test_op", source="personhog", client_name="posthog-django")

    @patch("posthog.personhog_client.metrics.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.personhog_client.metrics.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_reraise_as_wraps_exception(self, mock_errors, mock_routing):
        def failing_fn():
            raise RuntimeError("boom")

        with self.assertRaises(ValueError):
            personhog_call("test_op", failing_fn, reraise_as=ValueError)

        mock_errors.labels.return_value.inc.assert_called_once()
        mock_routing.labels.return_value.inc.assert_not_called()


# ── get_persons_mapped_by_distinct_id tests ────────────


class TestGetPersonsMappedByDistinctId(PersonhogTestMixin, BaseTest):
    def test_single_person_single_distinct_id(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1"], properties={"email": "a@example.com"})

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["did-1"])

        assert "did-1" in result
        assert str(result["did-1"].uuid) == str(person.uuid)
        assert result["did-1"].properties == {"email": "a@example.com"}
        assert result["did-1"].distinct_ids == ["did-1"]
        self._assert_personhog_called("get_persons_by_distinct_ids_in_team")

    def test_single_person_multiple_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1", "did-2"])

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["did-1", "did-2"])

        # Both distinct_ids should map to the same person
        assert len(result) == 2
        assert str(result["did-1"].uuid) == str(person.uuid)
        assert str(result["did-2"].uuid) == str(person.uuid)
        # Each entry should carry only the distinct_id that was used as the key
        assert result["did-1"].distinct_ids == ["did-1"]
        assert result["did-2"].distinct_ids == ["did-2"]

    def test_multiple_persons(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["alice"], properties={"name": "Alice"})
        p2 = self._seed_person(team=self.team, distinct_ids=["bob"], properties={"name": "Bob"})

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["alice", "bob"])

        assert str(result["alice"].uuid) == str(p1.uuid)
        assert str(result["bob"].uuid) == str(p2.uuid)

    def test_missing_distinct_ids_returns_empty(self):
        result = get_persons_mapped_by_distinct_id(self.team.pk, ["nonexistent"])

        assert result == {}

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        self._seed_person(team=other_team, distinct_ids=["shared_did"])

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["shared_did"])

        assert result == {}


# ── Public get_person_uuids_by_distinct_ids tests ─────────────────────


class TestGetPersonUuidsByDistinctIds(BaseTest):
    def _get_uuids(self, distinct_ids: list[str]) -> list[str]:
        return get_person_uuids_by_distinct_ids(self.team.pk, distinct_ids)

    def test_returns_uuids_for_matching_distinct_ids(self):
        p1 = create_person(team=self.team, distinct_ids=["d1", "d2"])
        p2 = create_person(team=self.team, distinct_ids=["d3"])

        result = self._get_uuids(["d1", "d3"])

        assert set(result) == {str(p1.uuid), str(p2.uuid)}
        get_active_fake().assert_called("get_persons_by_distinct_ids_in_team")

    def test_returns_empty_list_for_empty_input(self):
        result = self._get_uuids([])

        assert result == []
        get_active_fake().assert_not_called("get_persons_by_distinct_ids_in_team")

    def test_returns_empty_list_when_no_persons_match(self):
        result = self._get_uuids(["nonexistent"])

        assert result == []

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        create_person(team=other_team, distinct_ids=["d1"])

        result = self._get_uuids(["d1"])

        assert result == []

    def test_deduplicates_persons_with_multiple_distinct_ids(self):
        p = create_person(team=self.team, distinct_ids=["d1", "d2", "d3"])

        result = self._get_uuids(["d1", "d2", "d3"])

        assert result == [str(p.uuid)]

    def test_handles_mix_of_found_and_missing_distinct_ids(self):
        p = create_person(team=self.team, distinct_ids=["exists"])

        result = self._get_uuids(["exists", "missing1", "missing2"])

        assert result == [str(p.uuid)]

    def test_multiple_persons_each_with_single_distinct_id(self):
        persons = [create_person(team=self.team, distinct_ids=[f"d{i}"]) for i in range(5)]

        result = self._get_uuids([f"d{i}" for i in range(5)])

        assert set(result) == {str(p.uuid) for p in persons}


class TestGetPersonUuidsByDistinctIdsFieldMask(BaseTest):
    """Verify the personhog path sends a UUID-only field mask."""

    def test_sends_uuid_only_field_mask(self):
        create_person(team=self.team, distinct_ids=["d1"])

        get_person_uuids_by_distinct_ids(self.team.pk, ["d1"])

        fake = get_active_fake()
        calls = fake.assert_called("get_persons_by_distinct_ids_in_team", times=1)
        mask = list(calls[0].request.read_options.field_mask)
        assert "uuid" in mask
        assert "id" in mask
        assert "team_id" in mask
        assert "properties" not in mask
