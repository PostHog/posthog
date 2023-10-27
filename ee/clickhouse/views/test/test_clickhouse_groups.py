from unittest import mock
from uuid import UUID

from freezegun.api import freeze_time

from posthog.models import GroupTypeMapping, Person
from posthog.models.group.util import create_group
from posthog.models.organization import Organization
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team.team import Team
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    snapshot_clickhouse_queries,
)


class ClickhouseTestGroupsApi(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @freeze_time("2021-05-02")
    def test_groups_list(self):
        with freeze_time("2021-05-01"):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:5",
                properties={"industry": "finance", "name": "Mr. Krabs"},
            )
        with freeze_time("2021-05-02"):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:6",
                properties={"industry": "technology"},
            )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"name": "Plankton"},
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-02T00:00:00Z",
                        "group_key": "org:6",
                        "group_properties": {"industry": "technology"},
                        "group_type_index": 0,
                    },
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )
        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&search=Krabs").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&search=org:5").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )

    @freeze_time("2021-05-02")
    def test_groups_list_no_group_type(self):
        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/").json()
        self.assertEqual(
            response_data,
            {
                "type": "validation_error",
                "attr": "group_type_index",
                "code": "invalid_input",
                "detail": mock.ANY,
            },
        )

    @freeze_time("2021-05-02")
    def test_retrieve_group(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="key",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="foo//bar",
            properties={},
        )

        fail_response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index=1&group_key=key")
        self.assertEqual(fail_response.status_code, 404)

        ok_response_data = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index=0&group_key=key")
        self.assertEqual(ok_response_data.status_code, 200)
        self.assertEqual(
            ok_response_data.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "key",
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )
        ok_response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/find?group_type_index=1&group_key=foo//bar"
        )
        self.assertEqual(ok_response_data.status_code, 200)
        self.assertEqual(
            ok_response_data.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "foo//bar",
                "group_properties": {},
                "group_type_index": 1,
            },
        )

    @freeze_time("2021-05-10")
    @snapshot_clickhouse_queries
    def test_related_groups(self):
        self._create_related_groups_data()

        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/related?id=0::0&group_type_index=0"
        ).json()
        self.assertEqual(
            response_data,
            [
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "distinct_ids": ["1", "2"],
                    "id": "01795392-cc00-0003-7dc7-67a694604d72",
                    "uuid": "01795392-cc00-0003-7dc7-67a694604d72",
                    "is_identified": False,
                    "name": "1",
                    "properties": {},
                    "type": "person",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::2",
                    "group_type_index": 1,
                    "id": "1::2",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::3",
                    "group_type_index": 1,
                    "id": "1::3",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
            ],
        )

    @freeze_time("2021-05-10")
    @snapshot_clickhouse_queries
    def test_related_groups_person(self):
        uuid = self._create_related_groups_data()

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/related?id={uuid}").json()
        self.assertEqual(
            response_data,
            [
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "0::0",
                    "group_type_index": 0,
                    "id": "0::0",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "0::1",
                    "group_type_index": 0,
                    "id": "0::1",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::2",
                    "group_type_index": 1,
                    "id": "1::2",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::3",
                    "group_type_index": 1,
                    "id": "1::3",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
            ],
        )

    def test_property_definitions(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"name": "Plankton"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:2",
            properties={},
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/property_definitions").json()
        self.assertEqual(
            response_data,
            {
                "0": [{"name": "industry", "count": 2}, {"name": "name", "count": 1}],
                "1": [{"name": "name", "count": 1}],
            },
        )

    def test_property_values(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"industry": "finance"},
        )
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0"
        ).json()
        self.assertEqual(len(response_data), 2)
        self.assertEqual(response_data, [{"name": "finance"}, {"name": "technology"}])

    def test_empty_property_values(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"industry": "finance"},
        )
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=name&group_type_index=0"
        ).json()
        self.assertEqual(len(response_data), 0)
        self.assertEqual(response_data, [])

    def test_update_groups_metadata(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="playlist", group_type_index=1)
        GroupTypeMapping.objects.create(team=self.team, group_type="another", group_type_index=2)

        response_data = self.client.patch(
            f"/api/projects/{self.team.id}/groups_types/update_metadata",
            [
                {"group_type_index": 0, "name_singular": "organization!"},
                {
                    "group_type_index": 1,
                    "group_type": "rename attempt",
                    "name_plural": "playlists",
                },
            ],
        ).json()

        self.assertEqual(
            response_data,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": "organization!",
                    "name_plural": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": "playlists",
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                },
            ],
        )

    def test_list_group_types(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="playlist", group_type_index=1)
        GroupTypeMapping.objects.create(team=self.team, group_type="another", group_type_index=2)

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups_types").json()

        self.assertEqual(
            response_data,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": None,
                    "name_plural": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                },
            ],
        )

    def test_cannot_list_group_types_of_another_org(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")

        GroupTypeMapping.objects.create(team=other_team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=other_team, group_type="playlist", group_type_index=1)
        GroupTypeMapping.objects.create(team=other_team, group_type="another", group_type_index=2)

        response = self.client.get(f"/api/projects/{other_team.id}/groups_types")  # No access to this project

        self.assertEqual(response.status_code, 403, response.json())
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You don't have access to the project."),
        )

    def test_can_list_group_types_of_another_org_with_sharing_access_token(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")
        sharing_configuration = SharingConfiguration.objects.create(team=other_team, enabled=True)

        GroupTypeMapping.objects.create(team=other_team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=other_team, group_type="playlist", group_type_index=1)
        GroupTypeMapping.objects.create(team=other_team, group_type="another", group_type_index=2)

        disabled_response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types/?sharing_access_token={sharing_configuration.access_token}"
        ).json()

        self.assertEqual(
            disabled_response,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": None,
                    "name_plural": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                },
            ],
        )

        # Disable the config now
        sharing_configuration.enabled = False
        sharing_configuration.save()

        disabled_response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types?sharing_access_token={sharing_configuration.access_token}"
        )

        self.assertEqual(disabled_response.status_code, 403, disabled_response.json())
        self.assertEqual(
            disabled_response.json(),
            self.unauthenticated_response("Sharing access token is invalid.", "authentication_failed"),
        )

    def _create_related_groups_data(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="playlist", group_type_index=1)

        uuid = UUID("01795392-cc00-0003-7dc7-67a694604d72")

        Person.objects.create(uuid=uuid, team_id=self.team.pk, distinct_ids=["1", "2"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["3"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["4"])

        create_group(self.team.pk, 0, "0::0")
        create_group(self.team.pk, 0, "0::1")
        create_group(self.team.pk, 1, "1::2")
        create_group(self.team.pk, 1, "1::3")
        create_group(self.team.pk, 1, "1::4")
        create_group(self.team.pk, 1, "1::5")

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::2"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::3"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::1", "$group_1": "1::3"},
        )

        # Event too old, not counted
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2000-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::4"},
        )

        # No such group exists in groups table
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2000-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "no such group"},
        )

        return uuid
