import pytest

from posthog.test.base import TestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class CreatingSessionRecordingModelMigrationTestCase(TestMigrations):

    migrate_from = "0286_index_insightcachingstate_lookup"
    migrate_to = "0287_add_session_recording_model"

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        SessionRecordingPlaylist = apps.get_model("posthog", "SessionRecordingPlaylist")
        SessionRecordingPlaylistItem = apps.get_model("posthog", "SessionRecordingPlaylistItem")
        Team = apps.get_model("posthog", "Team")

        org = Organization.objects.create(name="o1")
        team = Team.objects.create(name="t1", organization=org)

        # CASE 0:
        # soft deleted playlist items
        # expect: 0 recording objects and playlist item is deleted
        playlist1 = SessionRecordingPlaylist.objects.create(name="p1", team=team)
        SessionRecordingPlaylistItem.objects.create(name="pi_0", session_id="s_0", playlist=playlist1, deleted=True)

        # CASE 1:
        # 2 playlist items for the same recording
        # expect: one recording object
        playlist2 = SessionRecordingPlaylist.objects.create(name="p2", team=team)
        playlist3 = SessionRecordingPlaylist.objects.create(name="p3", team=team)
        SessionRecordingPlaylistItem.objects.create(name="pi_1_1", session_id="s_1", playlist=playlist2)
        SessionRecordingPlaylistItem.objects.create(name="pi_1_2", session_id="s_1", playlist=playlist3)

        # CASE 2:
        # 2 playlist items for different recordings on different playlists
        # expect: 2 recording objects
        playlist4 = SessionRecordingPlaylist.objects.create(name="p4", team=team)
        playlist5 = SessionRecordingPlaylist.objects.create(name="p5", team=team)
        SessionRecordingPlaylistItem.objects.create(name="pi_2_1", session_id="s_2_1", playlist=playlist4)
        SessionRecordingPlaylistItem.objects.create(name="pi_2_2", session_id="s_2_2", playlist=playlist5)

        # CASE 3:
        # 2 playlist items for different recordings on same playlist
        # expect: 2 recording objects
        playlist6 = SessionRecordingPlaylist.objects.create(name="p6", team=team)
        SessionRecordingPlaylistItem.objects.create(name="pi_3_1", session_id="s_3_1", playlist=playlist6)
        SessionRecordingPlaylistItem.objects.create(name="pi_3_2", session_id="s_3_2", playlist=playlist6)

    def test_migrate_to_create_session_recordings(self):
        SessionRecording = self.apps.get_model("posthog", "SessionRecording")  # type: ignore
        SessionRecordingPlaylistItem = self.apps.get_model("posthog", "SessionRecordingPlaylistItem")  # type: ignore

        # CASE 0:
        self.assertEqual(SessionRecordingPlaylistItem.objects.filter(name="pi_0").count(), 0)
        self.assertEqual(SessionRecording.objects.filter(name="s_0").count(), 0)

        # CASE 1:
        self.assertEqual(SessionRecording.objects.filter(session_id="s_1").count(), 1)
        recording = SessionRecording.objects.get(session_id="s_1").first()
        self.assertEqual(recording.playlist_items[0].team.name, "t1")
        self.assertEqual(recording.playlist_items[0].playlist.name, "p2")
        self.assertEqual(recording.playlist_items[1].team.name, "t1")
        self.assertEqual(recording.playlist_items[1].playlist.name, "p3")

        # CASE 2:
        self.assertEqual(SessionRecording.objects.filter(session_id="s_2_1").count(), 1)
        self.assertEqual(SessionRecording.objects.filter(session_id="s_2_2").count(), 1)
        recording1 = SessionRecording.objects.get(session_id="s_2_1").first()
        self.assertEqual(recording1.team.name, "t1")
        self.assertEqual(recording1.playlist_items[0].playlist.name, "p4")
        recording2 = SessionRecording.objects.get(session_id="s_2_2").first()
        self.assertEqual(recording2.team.name, "t1")
        self.assertEqual(recording2.playlist_items[0].playlist.name, "p5")

        # CASE 3:
        self.assertEqual(SessionRecording.objects.filter(session_id="s_3_1").count(), 1)
        self.assertEqual(SessionRecording.objects.filter(session_id="s_3_2").count(), 1)
        recording1 = SessionRecording.objects.get(session_id="s_3_1").first()
        self.assertEqual(recording1.team.name, "t1")
        self.assertEqual(recording1.playlist_items[0].playlist.name, "p6")
        recording2 = SessionRecording.objects.get(session_id="s_3_2").first()
        self.assertEqual(recording2.team.name, "t1")
        self.assertEqual(recording2.playlist_items[0].playlist.name, "p6")

    def tearDown(self):
        SessionRecording = self.apps.get_model("posthog", "SessionRecording")  # type: ignore
        SessionRecordingPlaylistItem = self.apps.get_model("posthog", "SessionRecordingPlaylistItem")  # type: ignore
        SessionRecordingPlaylist = self.apps.get_model("posthog", "SessionRecordingPlaylist")  # type: ignore

        SessionRecording.objects.all().delete()
        SessionRecordingPlaylistItem.objects.all().delete()
        SessionRecordingPlaylist.objects.all().delete()
