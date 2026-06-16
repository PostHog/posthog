"""
Synthetic playlists are virtual playlists that are dynamically calculated and available to all users.
They are not stored in the database but appear alongside regular playlists in the API.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from django.core.cache import cache

from posthog.schema import RecordingOrder, RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Comment, Team, User
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.session_recording_api import list_recordings_from_query

from products.exports.backend.models.exported_asset import ExportedAsset

try:
    from products.replay.backend.models.session_summaries import SingleSessionSummary

    HAS_EE = True
except ImportError:
    HAS_EE = False


class GetSessionIdsCallable(Protocol):
    def __call__(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]: ...


class CountSessionIdsCallable(Protocol):
    def __call__(self, team: Team, user: User) -> int: ...


class SyntheticPlaylistSource(ABC):
    """
    Base class for synthetic playlist sources.
    Subclasses implement to_synthetic_playlist() to return one static playlist per source.
    """

    @staticmethod
    def _slice_indices(limit: int | None = None, offset: int | None = None) -> tuple[int, int | None]:
        start = offset or 0
        end = (start + limit) if limit is not None else None
        return start, end

    @staticmethod
    def _paginate_queryset(queryset, limit: int | None = None, offset: int | None = None):
        start, end = SyntheticPlaylistSource._slice_indices(limit, offset)
        return queryset[start:end]

    @staticmethod
    def _paginate_list(items: list[str], limit: int | None = None, offset: int | None = None) -> list[str]:
        start, end = SyntheticPlaylistSource._slice_indices(limit, offset)
        return items[start:end]

    @abstractmethod
    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        pass

    @abstractmethod
    def count_session_ids(self, team: Team, user: User) -> int:
        pass

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition | None":
        """
        Return a single static synthetic playlist definition.
        """
        return None


@dataclass
class WatchedPlaylistSource(SyntheticPlaylistSource):
    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        qs = SessionRecordingViewed.objects.filter(team=team, user=user).order_by("-created_at")
        return list(self._paginate_queryset(qs, limit, offset).values_list("session_id", flat=True))

    def count_session_ids(self, team: Team, user: User) -> int:
        return SessionRecordingViewed.objects.filter(team=team, user=user).count()

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition":
        return SyntheticPlaylistDefinition(
            id=-1,
            short_id="synthetic-watch-history",
            name="Watch history",
            description="Recordings you have watched",
            type="collection",
            get_session_ids=self.get_session_ids,
            count_session_ids=self.count_session_ids,
            metadata={"icon": "IconEye", "is_user_specific": True},
        )


@dataclass
class CommentedPlaylistSource(SyntheticPlaylistSource):
    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        qs = (
            Comment.objects.filter(team=team, scope="Replay", deleted=False)
            .exclude(item_id__isnull=True)
            .values_list("item_id", flat=True)
            .distinct()
        )
        return list(self._paginate_queryset(qs, limit, offset))

    def count_session_ids(self, team: Team, user: User) -> int:
        return (
            Comment.objects.filter(team=team, scope="Replay", deleted=False)
            .exclude(item_id__isnull=True)
            .values("item_id")
            .distinct()
            .count()
        )

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition":
        return SyntheticPlaylistDefinition(
            id=-2,
            short_id="synthetic-commented",
            name="Recordings with comments",
            description="Recordings that have team comments",
            type="collection",
            get_session_ids=self.get_session_ids,
            count_session_ids=self.count_session_ids,
            metadata={"icon": "IconComment", "is_user_specific": False},
        )


@dataclass
class SharedPlaylistSource(SyntheticPlaylistSource):
    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        qs = (
            SharingConfiguration.objects.filter(team=team, enabled=True)
            .exclude(recording__isnull=True)
            .values_list("recording__session_id", flat=True)
            .distinct()
        )
        return list(self._paginate_queryset(qs, limit, offset))

    def count_session_ids(self, team: Team, user: User) -> int:
        return (
            SharingConfiguration.objects.filter(team=team, enabled=True)
            .exclude(recording__isnull=True)
            .values("recording__session_id")
            .distinct()
            .count()
        )

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition":
        return SyntheticPlaylistDefinition(
            id=-3,
            short_id="synthetic-shared",
            name="Shared recordings",
            description="Recordings that have been shared externally",
            type="collection",
            get_session_ids=self.get_session_ids,
            count_session_ids=self.count_session_ids,
            metadata={"icon": "IconShare", "is_user_specific": False},
        )


@dataclass
class ExportedPlaylistSource(SyntheticPlaylistSource):
    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        qs = (
            ExportedAsset.objects.filter(team=team)
            .filter(export_context__has_key="session_recording_id")
            .exclude(export_context__session_recording_id__isnull=True)
            .exclude(export_context__session_recording_id="")
            .order_by("-created_at")
            .values_list("export_context__session_recording_id", flat=True)
        )
        session_ids = list(dict.fromkeys(qs))
        return self._paginate_list(session_ids, limit, offset)

    def count_session_ids(self, team: Team, user: User) -> int:
        return (
            ExportedAsset.objects.filter(team=team)
            .filter(export_context__has_key="session_recording_id")
            .exclude(export_context__session_recording_id__isnull=True)
            .exclude(export_context__session_recording_id="")
            .values("export_context__session_recording_id")
            .distinct()
            .count()
        )

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition":
        return SyntheticPlaylistDefinition(
            id=-4,
            short_id="synthetic-exported",
            name="Exported recordings",
            description="Recordings that have been exported as clips or screenshots",
            type="collection",
            get_session_ids=self.get_session_ids,
            count_session_ids=self.count_session_ids,
            metadata={"icon": "IconDownload", "is_user_specific": False},
        )


@dataclass
class SummarisedPlaylistSource(SyntheticPlaylistSource):
    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        if not HAS_EE:
            return []
        qs = (
            SingleSessionSummary.objects.filter(team=team)
            .order_by("-created_at")
            .values_list("session_id", flat=True)
            .distinct()
        )
        return list(self._paginate_queryset(qs, limit, offset))

    def count_session_ids(self, team: Team, user: User) -> int:
        if not HAS_EE:
            return 0
        return SingleSessionSummary.objects.filter(team=team).values("session_id").distinct().count()

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition":
        return SyntheticPlaylistDefinition(
            id=-5,
            short_id="synthetic-summarised",
            name="Summarised sessions",
            description="Sessions with AI-generated summaries. Ask PostHog AI to summarize sessions for you.",
            type="collection",
            get_session_ids=self.get_session_ids,
            count_session_ids=self.count_session_ids,
            metadata={"icon": "IconSparkles", "is_user_specific": False},
        )


@dataclass
class ExpiringPlaylistSource(SyntheticPlaylistSource):
    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        fetch_limit = ((offset or 0) + (limit or 50)) * 2
        query = RecordingsQuery(limit=fetch_limit, order=RecordingOrder.RECORDING_TTL)
        recordings, _, _, _ = list_recordings_from_query(query, user, team)

        now = datetime.now(UTC)
        ten_days_from_now = now + timedelta(days=10)

        result = [r.session_id for r in recordings if r.expiry_time and now <= r.expiry_time <= ten_days_from_now]
        return self._paginate_list(result, limit, offset)

    def count_session_ids(self, team: Team, user: User) -> int:
        query = RecordingsQuery(limit=10000, order=RecordingOrder.RECORDING_TTL)
        recordings, _, _, _ = list_recordings_from_query(query, user, team)

        now = datetime.now(UTC)
        ten_days_from_now = now + timedelta(days=10)

        return sum(1 for r in recordings if r.expiry_time and now <= r.expiry_time <= ten_days_from_now)

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition":
        return SyntheticPlaylistDefinition(
            id=-6,
            short_id="synthetic-expiring",
            name="Expiring soon",
            description="Recordings that will expire in the next 10 days",
            type="collection",
            get_session_ids=self.get_session_ids,
            count_session_ids=self.count_session_ids,
            metadata={"icon": "IconClock", "is_user_specific": False},
        )


@dataclass
class FrustrationSignalsPlaylistSource(SyntheticPlaylistSource):
    """
    Surfaces sessions with frustration signals: rage clicks and exceptions.
    Results are cached for 1 hour and ranked by a composite frustration score.
    """

    CACHE_KEY_PREFIX = "frustration_signals_synthetic_playlist"
    CACHE_TTL = 3600  # 1 hour
    LOOKBACK_DAYS = 7
    MIN_FRUSTRATION_SCORE = 5

    @staticmethod
    def _get_cache_key(team_id: int) -> str:
        return f"{FrustrationSignalsPlaylistSource.CACHE_KEY_PREFIX}_team_{team_id}"

    @staticmethod
    def _get_frustrated_session_ids(team: Team) -> list[str]:
        """
        Query ClickHouse for sessions with frustration signals in the last 7 days.
        Returns session_ids ordered by composite frustration score (descending).
        Cached for 1 hour.
        """
        cache_key = FrustrationSignalsPlaylistSource._get_cache_key(team.pk)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        now_ts = datetime.now(UTC)
        date_from = now_ts - timedelta(days=FrustrationSignalsPlaylistSource.LOOKBACK_DAYS)

        query = """
            SELECT
                `$session_id` AS session_id,
                countIf(event = '$rageclick') * 3
                    + countIf(event = '$exception') * 2
                    AS frustration_score
            FROM events
            WHERE
                team_id = %(team_id)s
                AND event IN ('$rageclick', '$exception')
                AND timestamp >= %(date_from)s
                AND timestamp <= %(date_to)s
                AND notEmpty(`$session_id`)
            GROUP BY `$session_id`
            HAVING frustration_score > %(min_frustration_score)s
            ORDER BY frustration_score DESC
            LIMIT 1000
        """

        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
        result = sync_execute(
            query,
            {
                "team_id": team.pk,
                "date_from": date_from,
                "date_to": now_ts,
                "min_frustration_score": FrustrationSignalsPlaylistSource.MIN_FRUSTRATION_SCORE,
            },
        )

        session_ids = [row[0] for row in result]
        cache.set(cache_key, session_ids, FrustrationSignalsPlaylistSource.CACHE_TTL)
        return session_ids

    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        session_ids = self._get_frustrated_session_ids(team)
        return self._paginate_list(session_ids, limit, offset)

    def count_session_ids(self, team: Team, user: User) -> int:
        return len(self._get_frustrated_session_ids(team))

    def to_synthetic_playlist(self) -> "SyntheticPlaylistDefinition":
        return SyntheticPlaylistDefinition(
            id=-7,
            short_id="synthetic-frustrated",
            name="Frustration signals",
            description="Sessions with rage clicks or errors in the last 7 days",
            type="collection",
            get_session_ids=self.get_session_ids,
            count_session_ids=self.count_session_ids,
            metadata={"icon": "IconWarning", "is_user_specific": False},
        )


@dataclass
class SyntheticPlaylistDefinition:
    """Definition of a synthetic playlist that will be computed on-demand"""

    id: int
    short_id: str
    name: str
    description: str
    type: str  # Should be "collection"
    get_session_ids: GetSessionIdsCallable
    count_session_ids: CountSessionIdsCallable
    # Synthetic playlists don't have filters,
    # but we can store metadata about how they're generated
    metadata: dict


# Registry of static synthetic playlists
def _get_static_synthetic_playlists() -> list[SyntheticPlaylistDefinition]:
    playlists = [
        WatchedPlaylistSource().to_synthetic_playlist(),
        CommentedPlaylistSource().to_synthetic_playlist(),
        SharedPlaylistSource().to_synthetic_playlist(),
        ExportedPlaylistSource().to_synthetic_playlist(),
        ExpiringPlaylistSource().to_synthetic_playlist(),
        FrustrationSignalsPlaylistSource().to_synthetic_playlist(),
    ]

    # Only add summarised playlist if EE is available
    if HAS_EE:
        playlists.append(SummarisedPlaylistSource().to_synthetic_playlist())

    # Filter out None values (sources that only generate dynamic playlists)
    return [p for p in playlists if p is not None]


# fixed list of synthetic playlists, including Watch History, Expiring Soon, etc
SYNTHETIC_PLAYLISTS: list[SyntheticPlaylistDefinition] = _get_static_synthetic_playlists()


def get_synthetic_playlist(short_id: str, team: Team | None = None) -> SyntheticPlaylistDefinition | None:
    """
    Get a synthetic playlist by short_id.
    """
    for playlist in SYNTHETIC_PLAYLISTS:
        if playlist.short_id == short_id:
            return playlist

    return None


def get_all_synthetic_playlists(team: Team) -> list[SyntheticPlaylistDefinition]:
    """
    Get all synthetic playlists for a team.
    """
    return list(SYNTHETIC_PLAYLISTS)
