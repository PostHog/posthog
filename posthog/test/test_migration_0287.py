from posthog.test.base import NonAtomicTestMigrations

import pytest

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class CreatingSessionRecordingModelMigrationTestCase(NonAtomicTestMigrations):
    migrate_from = "0286_index_insightcachingstate_lookup"
    migrate_to = "0287_add_session_recording_model"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Team = apps.get_model("posthog", "Team")
        SessionRecordingPlaylist = apps.get_model("posthog", "SessionRecordingPlaylist")
        SessionRecordingPlaylistItem = apps.get_model("posthog", "SessionRecordingPlaylistItem")

        org = Organization.objects.create(name="o1")
        team = Team.objects.create(name="t1", organization=org)

        # CASE 0:
        # soft deleted playlist items
        # expect: 0 recording objects and playlist item is deleted
        playlist1 = SessionRecordingPlaylist.objects.create(name="p1", team=team)
        SessionRecordingPlaylistItem.objects.create(session_id="s_0", playlist=playlist1, deleted=True)

        # CASE 1:
        # 2 playlist items for the same recording
        # expect: one recording object
        playlist2 = SessionRecordingPlaylist.objects.create(name="p2", team=team)
        playlist3 = SessionRecordingPlaylist.objects.create(name="p3", team=team)
        SessionRecordingPlaylistItem.objects.create(session_id="s_1", playlist=playlist2)
        SessionRecordingPlaylistItem.objects.create(session_id="s_1", playlist=playlist3)

        # CASE 2:
        # 2 playlist items for different recordings on different playlists
        # expect: 2 recording objects
        playlist4 = SessionRecordingPlaylist.objects.create(name="p4", team=team)
        playlist5 = SessionRecordingPlaylist.objects.create(name="p5", team=team)
        SessionRecordingPlaylistItem.objects.create(session_id="s_2_1", playlist=playlist4)
        SessionRecordingPlaylistItem.objects.create(session_id="s_2_2", playlist=playlist5)

        # CASE 3:
        # 2 playlist items for different recordings on same playlist
        # expect: 2 recording objects
        playlist6 = SessionRecordingPlaylist.objects.create(name="p6", team=team)
        SessionRecordingPlaylistItem.objects.create(session_id="s_3_1", playlist=playlist6)
        SessionRecordingPlaylistItem.objects.create(session_id="s_3_2", playlist=playlist6)

    def test_migrate_to_create_session_recordings(self):
        SessionRecording = self.apps.get_model("posthog", "SessionRecording")  # type: ignore
        SessionRecordingPlaylist = self.apps.get_model("posthog", "SessionRecordingPlaylist")  # type: ignore
        SessionRecordingPlaylistItem = self.apps.get_model("posthog", "SessionRecordingPlaylistItem")  # type: ignore

        # CASE 0:
        playlist = SessionRecordingPlaylist.objects.get(name="p1")
        assert SessionRecordingPlaylistItem.objects.filter(playlist=playlist, deleted=False).count() == 0
        assert SessionRecording.objects.filter(session_id="s_0").count() == 0

        # CASE 1:
        assert SessionRecording.objects.filter(session_id="s_1").count() == 1
        playlist_items = SessionRecordingPlaylistItem.objects.filter(session_id="s_1").select_related("playlist").all()
        assert len(playlist_items) == 2
        assert playlist_items[0].playlist.name == "p2"
        assert playlist_items[1].playlist.name == "p3"

        # CASE 2:
        assert SessionRecording.objects.filter(session_id="s_2_1").count() == 1
        assert SessionRecording.objects.filter(session_id="s_2_2").count() == 1

        playlist_items = (
            SessionRecordingPlaylistItem.objects.filter(session_id="s_2_1").select_related("playlist").all()
        )
        assert len(playlist_items) == 1
        assert playlist_items[0].playlist.name == "p4"

        playlist_items = (
            SessionRecordingPlaylistItem.objects.filter(session_id="s_2_2").select_related("playlist").all()
        )
        assert len(playlist_items) == 1
        assert playlist_items[0].playlist.name == "p5"

        # CASE 3:
        assert SessionRecording.objects.filter(session_id="s_3_1").count() == 1
        assert SessionRecording.objects.filter(session_id="s_3_2").count() == 1
        playlist_items = SessionRecordingPlaylistItem.objects.filter(playlist__name="p6").all()

        assert len(playlist_items) == 2
        assert playlist_items[0].recording_id == "s_3_1"
        assert playlist_items[1].recording_id == "s_3_2"

    def tearDown(self):
        Organization = self.apps.get_model("posthog", "Organization")  # type: ignore
        Team = self.apps.get_model("posthog", "Team")  # type: ignore
        SessionRecording = self.apps.get_model("posthog", "SessionRecording")  # type: ignore
        SessionRecordingPlaylistItem = self.apps.get_model("posthog", "SessionRecordingPlaylistItem")  # type: ignore
        SessionRecordingPlaylist = self.apps.get_model("posthog", "SessionRecordingPlaylist")  # type: ignore

        SessionRecording.objects.all().delete()
        SessionRecordingPlaylistItem.objects.all().delete()
        SessionRecordingPlaylist.objects.all().delete()
        Team.objects.all().delete()
        Organization.objects.all().delete()
