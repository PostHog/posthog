"""
Synthetic playlists are virtual playlists that are dynamically calculated and available to all users.
They are not stored in the database but appear alongside regular playlists in the API.
"""

from collections.abc import Callable
from dataclasses import dataclass

from posthog.models import Comment, Team, User
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed

try:
    from ee.models.session_summaries import SingleSessionSummary

    HAS_EE = True
except ImportError:
    HAS_EE = False


@dataclass
class SyntheticPlaylistDefinition:
    """Definition of a synthetic playlist that will be computed on-demand"""

    short_id: str
    name: str
    description: str
    type: str  # Should be "collection"
    get_session_ids: Callable[[Team, User], list[str]]
    # Synthetic playlists don't have filters in the traditional sense,
    # but we can store metadata about how they're generated
    metadata: dict


def get_watched_session_ids(team: Team, user: User) -> list[str]:
    """Get all session IDs the user has watched"""
    return list(
        SessionRecordingViewed.objects.filter(team=team, user=user)
        .order_by("-created_at")
        .values_list("session_id", flat=True)[:1000]  # Limit to most recent 1000
    )


def get_commented_session_ids(team: Team, user: User) -> list[str]:
    """Get all session IDs that have comments from anyone on the team"""
    return list(
        Comment.objects.filter(team=team, scope="Replay", deleted=False)
        .exclude(item_id__isnull=True)
        .values_list("item_id", flat=True)
        .distinct()[:1000]  # Limit to 1000
    )


def get_shared_session_ids(team: Team, user: User) -> list[str]:
    """Get all session IDs that have been shared"""
    return list(
        SharingConfiguration.objects.filter(team=team, enabled=True)
        .exclude(recording__isnull=True)
        .values_list("recording__session_id", flat=True)
        .distinct()[:1000]  # Limit to 1000
    )


def get_summarised_session_ids(team: Team, user: User) -> list[str]:
    """Get all session IDs that have AI-generated summaries"""
    if not HAS_EE:
        return []

    return list(
        SingleSessionSummary.objects.filter(team=team)
        .order_by("-created_at")
        .values_list("session_id", flat=True)
        .distinct()[:1000]  # Limit to most recent 1000
    )


# Registry of all synthetic playlists
def _get_synthetic_playlists() -> list[SyntheticPlaylistDefinition]:
    """Build the list of synthetic playlists, conditionally including EE features"""
    playlists = [
        SyntheticPlaylistDefinition(
            short_id="synthetic-watch-history",
            name="Watch history",
            description="Recordings you have watched",
            type="collection",
            get_session_ids=get_watched_session_ids,
            metadata={"icon": "IconEye", "is_user_specific": True},
        ),
        SyntheticPlaylistDefinition(
            short_id="synthetic-commented",
            name="Recordings with comments",
            description="Recordings that have team comments",
            type="collection",
            get_session_ids=get_commented_session_ids,
            metadata={"icon": "IconComment", "is_user_specific": False},
        ),
        SyntheticPlaylistDefinition(
            short_id="synthetic-shared",
            name="Shared recordings",
            description="Recordings that have been shared externally",
            type="collection",
            get_session_ids=get_shared_session_ids,
            metadata={"icon": "IconShare", "is_user_specific": False},
        ),
    ]

    # Only add summarised playlist if EE is available
    if HAS_EE:
        playlists.append(
            SyntheticPlaylistDefinition(
                short_id="synthetic-summarised",
                name="Summarised sessions",
                description="Sessions with AI-generated summaries",
                type="collection",
                get_session_ids=get_summarised_session_ids,
                metadata={"icon": "IconSparkles", "is_user_specific": False},
            )
        )

    return playlists


SYNTHETIC_PLAYLISTS: list[SyntheticPlaylistDefinition] = _get_synthetic_playlists()


def get_synthetic_playlist(short_id: str) -> SyntheticPlaylistDefinition | None:
    """Get a synthetic playlist definition by short_id"""
    for playlist in SYNTHETIC_PLAYLISTS:
        if playlist.short_id == short_id:
            return playlist
    return None
