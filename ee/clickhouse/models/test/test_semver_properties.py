from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person

from posthog.clickhouse.client import sync_execute
from posthog.models.property import Property
from posthog.models.property.util import prop_filter_json_extract


class TestSemverPropertyFiltering(ClickhouseTestMixin, BaseTest):
    """Tests for semantic version (semver) property filtering operators."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        # Create test persons with various version strings
        self.person_v1_0_0 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["user1"],
            properties={"app_version": "1.0.0"},
        )
        self.person_v1_2_3 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["user2"],
            properties={"app_version": "1.2.3"},
        )
        self.person_v1_2_5 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["user3"],
            properties={"app_version": "1.2.5"},
        )
        self.person_v1_3_0 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["user4"],
            properties={"app_version": "1.3.0"},
        )
        self.person_v2_0_0 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["user5"],
            properties={"app_version": "2.0.0"},
        )
        self.person_v10_0_0 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["user6"],
            properties={"app_version": "10.0.0"},
        )

    def _query_persons(self, property: Property) -> list[str]:
        """Query persons matching the given property filter."""
        query, params = prop_filter_json_extract(
            property,
            0,
            prepend="",
            property_operator="AND",
            allow_denormalized_props=False,
        )
        return sorted(
            [
                str(uuid)
                for (uuid,) in sync_execute(
                    f"SELECT id FROM person WHERE team_id = %(team_id)s {query} AND is_deleted = 0",
                    {"team_id": self.team.pk, **params},
                )
            ]
        )

    def test_semver_gt(self):
        """Test semver greater than operator."""
        prop = Property(key="app_version", value="1.2.3", operator="semver_gt", type="person")
        results = self._query_persons(prop)
        expected = sorted(
            [
                str(self.person_v1_2_5.uuid),
                str(self.person_v1_3_0.uuid),
                str(self.person_v2_0_0.uuid),
                str(self.person_v10_0_0.uuid),
            ]
        )
        assert results == expected

    def test_semver_gte(self):
        """Test semver greater than or equal operator."""
        prop = Property(key="app_version", value="1.2.3", operator="semver_gte", type="person")
        results = self._query_persons(prop)
        expected = sorted(
            [
                str(self.person_v1_2_3.uuid),
                str(self.person_v1_2_5.uuid),
                str(self.person_v1_3_0.uuid),
                str(self.person_v2_0_0.uuid),
                str(self.person_v10_0_0.uuid),
            ]
        )
        assert results == expected

    def test_semver_lt(self):
        """Test semver less than operator."""
        prop = Property(key="app_version", value="1.2.5", operator="semver_lt", type="person")
        results = self._query_persons(prop)
        expected = sorted([str(self.person_v1_0_0.uuid), str(self.person_v1_2_3.uuid)])
        assert results == expected

    def test_semver_lte(self):
        """Test semver less than or equal operator."""
        prop = Property(key="app_version", value="1.2.5", operator="semver_lte", type="person")
        results = self._query_persons(prop)
        expected = sorted([str(self.person_v1_0_0.uuid), str(self.person_v1_2_3.uuid), str(self.person_v1_2_5.uuid)])
        assert results == expected

    def test_semver_eq(self):
        """Test semver equals operator."""
        prop = Property(key="app_version", value="1.2.3", operator="semver_eq", type="person")
        results = self._query_persons(prop)
        expected = sorted([str(self.person_v1_2_3.uuid)])
        assert results == expected

    def test_semver_neq(self):
        """Test semver not equals operator."""
        prop = Property(key="app_version", value="1.2.3", operator="semver_neq", type="person")
        results = self._query_persons(prop)
        expected = sorted(
            [
                str(self.person_v1_0_0.uuid),
                str(self.person_v1_2_5.uuid),
                str(self.person_v1_3_0.uuid),
                str(self.person_v2_0_0.uuid),
                str(self.person_v10_0_0.uuid),
            ]
        )
        assert results == expected

    def test_semver_gt_handles_double_digit_versions(self):
        """Test that semver comparison handles 10.x.x > 9.x.x correctly (not string comparison)."""
        prop = Property(key="app_version", value="9.0.0", operator="semver_gt", type="person")
        results = self._query_persons(prop)
        # 10.0.0 should be greater than 9.0.0 (unlike string comparison where "10" < "9")
        assert str(self.person_v10_0_0.uuid) in results

    def test_semver_tilde(self):
        """Test semver tilde operator (~1.2.3 means >=1.2.3 <1.3.0)."""
        prop = Property(key="app_version", value="1.2.3", operator="semver_tilde", type="person")
        results = self._query_persons(prop)
        # Should match 1.2.3 and 1.2.5, but not 1.3.0 or 2.0.0
        expected = sorted([str(self.person_v1_2_3.uuid), str(self.person_v1_2_5.uuid)])
        assert results == expected

    def test_semver_caret(self):
        """Test semver caret operator (^1.2.3 means >=1.2.3 <2.0.0)."""
        prop = Property(key="app_version", value="1.2.3", operator="semver_caret", type="person")
        results = self._query_persons(prop)
        # Should match 1.2.3, 1.2.5, and 1.3.0, but not 2.0.0
        expected = sorted([str(self.person_v1_2_3.uuid), str(self.person_v1_2_5.uuid), str(self.person_v1_3_0.uuid)])
        assert results == expected

    def test_semver_wildcard_patch(self):
        """Test semver wildcard operator for patch level (1.2.* means any 1.2.x)."""
        prop = Property(key="app_version", value="1.2.*", operator="semver_wildcard", type="person")
        results = self._query_persons(prop)
        # Should match 1.2.3 and 1.2.5
        expected = sorted([str(self.person_v1_2_3.uuid), str(self.person_v1_2_5.uuid)])
        assert results == expected

    def test_semver_wildcard_minor(self):
        """Test semver wildcard operator for minor level (1.*.* means any 1.x.x)."""
        prop = Property(key="app_version", value="1.*.*", operator="semver_wildcard", type="person")
        results = self._query_persons(prop)
        # Should match all 1.x.x versions
        expected = sorted(
            [
                str(self.person_v1_0_0.uuid),
                str(self.person_v1_2_3.uuid),
                str(self.person_v1_2_5.uuid),
                str(self.person_v1_3_0.uuid),
            ]
        )
        assert results == expected
