from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person.divergence.flavors import (
    ChMapping,
    ChPerson,
    PgMapping,
    PgPerson,
    RepairVerb,
    Verdict,
    classify_mapping,
    classify_person,
)


def _v(flavor: str, sub_flavor: str | None, verb: RepairVerb | None) -> Verdict:
    return Verdict(flavor=flavor, sub_flavor=sub_flavor, verb=verb)


def _ch(
    *,
    live: int | None = None,
    tomb: int | None = None,
    visible_rows: int = 1,
    rows_at_max: int = 1,
    payloads_at_max: int = 1,
    blanked: bool = False,
    masked_max: int | None = None,
) -> ChPerson:
    visible = [v for v in (live, tomb) if v is not None]
    return ChPerson(
        max_version=masked_max if masked_max is not None else max(visible, default=0),
        visible_rows=visible_rows,
        live_max_version=live,
        tombstone_max_version=tomb,
        rows_at_max=rows_at_max,
        payloads_at_max=payloads_at_max,
        winner_blanked=blanked,
    )


def _pg(version: int, *, deleted: bool = False, has_live_mappings: bool | None = None) -> PgPerson:
    return PgPerson(id=1, version=version, is_deleted=deleted, has_live_mappings=has_live_mappings)


class TestClassifyPerson(SimpleTestCase):
    @parameterized.expand(
        [
            ("absent_everywhere", None, None, True, _v("ok_deleted", None, None)),
            ("ch_only_tombstoned", None, _ch(tomb=3), True, _v("ok_deleted", None, None)),
            ("ch_only_swept", None, _ch(live=3, visible_rows=0), True, _v("ok_deleted", None, None)),
            ("ghost_historical", None, _ch(live=3), True, _v("ghost", "historical", None)),
            ("ghost_of_deleted_team", None, _ch(live=3), False, _v("ghost", "team_gone", None)),
            (
                "deleted_and_ch_newer",
                _pg(2, deleted=True),
                _ch(live=5, tomb=2),
                True,
                _v("deleted_visible", None, "bury"),
            ),
            (
                "deleted_and_ch_tie",
                _pg(4, deleted=True),
                _ch(live=4, tomb=4),
                True,
                _v("deleted_visible", None, "bury"),
            ),
            (
                "deleted_never_published",
                _pg(4, deleted=True),
                _ch(live=3),
                True,
                _v("deleted_visible", None, "bury"),
            ),
            (
                "deleted_and_published",
                _pg(4, deleted=True),
                _ch(live=3, tomb=4),
                True,
                _v("ok_deleted", None, None),
            ),
            ("deleted_and_swept", _pg(4, deleted=True), None, True, _v("ok_deleted", None, None)),
            ("live_missing_in_ch", _pg(2), None, True, _v("missing_in_ch", None, "republish")),
            (
                "live_and_swept",
                _pg(2),
                _ch(live=2, visible_rows=0, masked_max=105),
                True,
                _v("swept", None, "republish"),
            ),
            ("live_hidden_by_tombstone", _pg(2), _ch(live=2, tomb=102), True, _v("hidden", None, "republish")),
            ("live_and_stale", _pg(2), _ch(live=40), True, _v("stale", None, "merge_stale")),
            ("live_and_behind", _pg(9), _ch(live=4), True, _v("behind", None, "republish")),
            (
                "live_tie",
                _pg(4),
                _ch(live=4, rows_at_max=2, payloads_at_max=2),
                True,
                _v("tie", None, "republish"),
            ),
            (
                "live_duplicate_row_is_not_a_tie",
                _pg(4),
                _ch(live=4, rows_at_max=2, payloads_at_max=1),
                True,
                _v("ok", None, None),
            ),
            ("live_blanked", _pg(105), _ch(live=105, blanked=True), True, _v("blanked", None, "republish")),
            (
                "live_without_mappings",
                _pg(2, has_live_mappings=False),
                _ch(live=2),
                True,
                _v("no_live_mappings", None, None),
            ),
            ("live_and_equal", _pg(2, has_live_mappings=True), _ch(live=2), True, _v("ok", None, None)),
        ]
    )
    def test_classifies(self, _name, pg, ch, team_exists, expected):
        assert classify_person(pg, ch, team_exists=team_exists) == expected

    def test_ghost_after_a_purge_is_restored(self):
        assert classify_person(None, _ch(live=3), ghost_era="after_purge") == _v("ghost", "after_purge", "restore")


def _pg_map(
    *, version: int = 0, deleted: bool = False, owner: str | None = "b", owner_deleted: bool | None = False
) -> PgMapping:
    return PgMapping(
        person_id=1, person_uuid=owner, version=version, is_deleted=deleted, person_is_deleted=owner_deleted
    )


def _ch_map(*, owner: str = "b", version: int = 0, deleted: bool = False, visible_rows: int = 1) -> ChMapping:
    return ChMapping(
        max_version=version,
        visible_rows=visible_rows,
        winner_person_uuid=owner,
        winner_version=version,
        winner_deleted=deleted,
    )


class TestClassifyMapping(SimpleTestCase):
    @parameterized.expand(
        [
            ("absent_everywhere", None, None, None, _v("ok_deleted", None, None)),
            ("ch_only_tombstoned", None, _ch_map(deleted=True), None, _v("ok_deleted", None, None)),
            ("ghost_of_a_ghost_person", None, _ch_map(owner="a"), "absent", _v("ghost", "owner_ghost", "restore")),
            ("ghost_of_a_live_person", None, _ch_map(owner="a"), "live", _v("ghost", "owner_live", "restore")),
            ("ghost_of_a_deleted_person", None, _ch_map(owner="a"), "deleted", _v("ghost", "owner_deleted", None)),
            (
                "deleted_and_ch_live_above",
                _pg_map(version=2, deleted=True),
                _ch_map(version=3),
                None,
                _v("deleted_visible", None, "bury"),
            ),
            (
                "deleted_and_never_published",
                _pg_map(version=2, deleted=True),
                _ch_map(version=1),
                None,
                _v("deleted_visible", None, "bury"),
            ),
            (
                "deleted_and_published",
                _pg_map(version=2, deleted=True),
                _ch_map(version=2, deleted=True),
                None,
                _v("ok_deleted", None, None),
            ),
            (
                "stray_on_deleted_person",
                _pg_map(owner_deleted=True),
                _ch_map(),
                None,
                _v("stray", None, None),
            ),
            (
                "orphan_with_ch_on_another_person",
                _pg_map(owner=None, owner_deleted=None),
                _ch_map(owner="a"),
                "absent",
                _v("stray", None, None),
            ),
            ("live_missing_in_ch", _pg_map(), None, None, _v("missing_in_ch", None, "republish")),
            ("live_and_swept", _pg_map(), _ch_map(visible_rows=0), None, _v("missing_in_ch", None, "republish")),
            ("live_hidden", _pg_map(), _ch_map(deleted=True), None, _v("hidden", None, "republish")),
            (
                "diverged_old_owner_absent",
                _pg_map(),
                _ch_map(owner="a"),
                "absent",
                _v("diverged", "a_absent", "fold"),
            ),
            ("diverged_old_owner_live", _pg_map(), _ch_map(owner="a"), "live", _v("diverged", "a_live", "merge")),
            (
                "diverged_old_owner_deleted",
                _pg_map(),
                _ch_map(owner="a"),
                "deleted",
                _v("diverged", "a_deleted", "republish"),
            ),
            ("diverged_old_owner_unknown", _pg_map(), _ch_map(owner="a"), None, _v("diverged", "a_unknown", None)),
            ("stale_same_owner", _pg_map(version=1), _ch_map(version=5), None, _v("stale", None, "republish")),
            ("ok", _pg_map(version=5), _ch_map(version=5), None, _v("ok", None, None)),
        ]
    )
    def test_classifies(self, _name, pg, ch, owner_state, expected):
        assert classify_mapping(pg, ch, ch_owner_pg_state=owner_state) == expected

    def test_ghost_of_a_deleted_team_is_left_alone(self):
        assert classify_mapping(None, _ch_map(owner="a"), ch_owner_pg_state="absent", team_exists=False) == _v(
            "ghost", "team_gone", None
        )
