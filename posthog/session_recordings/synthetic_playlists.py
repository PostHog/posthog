"""
Synthetic playlists are virtual playlists that are dynamically calculated and available to all users.
They are not stored in the database but appear alongside regular playlists in the API.
"""

import re
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse

from django.core.cache import cache

import posthoganalytics

from posthog.schema import RecordingOrder, RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.models import Comment, Team, User
from posthog.models.exported_asset import ExportedAsset
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.session_recording_api import list_recordings_from_query

try:
    from ee.models.session_summaries import SingleSessionSummary

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
    Subclasses can implement either:
    1. to_synthetic_playlist() for static playlists (one playlist per source)
    2. generate_dynamic_playlists() for dynamic playlists (multiple playlists generated on-demand)
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
        Return None if this source only generates dynamic playlists.
        """
        return None

    def generate_dynamic_playlists(self, team: Team) -> list["SyntheticPlaylistDefinition"]:
        """
        Generate multiple dynamic playlist definitions for this source.
        Override this method to create playlists that vary based on data (e.g., one per URL).
        Return empty list if this source only generates a static playlist.
        """
        return []

    def get_dynamic_playlist_by_id(self, short_id: str, team: Team) -> "SyntheticPlaylistDefinition | None":
        """
        Retrieve a specific dynamic playlist by its short_id.
        Override this method for dynamic playlist sources.
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
        recordings, _, _ = list_recordings_from_query(query, user, team)

        now = datetime.now(UTC)
        ten_days_from_now = now + timedelta(days=10)

        result = [r.session_id for r in recordings if r.expiry_time and now <= r.expiry_time <= ten_days_from_now]
        return self._paginate_list(result, limit, offset)

    def count_session_ids(self, team: Team, user: User) -> int:
        query = RecordingsQuery(limit=10000, order=RecordingOrder.RECORDING_TTL)
        recordings, _, _ = list_recordings_from_query(query, user, team)

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
class NewUrlsSyntheticPlaylistSource(SyntheticPlaylistSource):
    """
    Dynamic synthetic playlist source that creates one playlist per new URL detected in the last 14 days.
    A URL is considered "new" if it first appeared in recordings within the last 14 days, and not previously seen within the last 90 days.
    """

    url: str | None = None

    CACHE_KEY_PREFIX = "new_urls_synthetic_playlist"
    CACHE_TTL = 3600  # 1 hour
    LOOKBACK_DAYS = 14
    MIN_ID = -1000  # Start IDs from -1000 for new URL playlists

    @staticmethod
    def _get_cache_key(team_id: int) -> str:
        """Generate cache key for new URLs list"""
        return f"{NewUrlsSyntheticPlaylistSource.CACHE_KEY_PREFIX}_team_{team_id}"

    @staticmethod
    def _url_to_hash(url: str) -> str:
        """Convert URL to a stable short hash for use in short_id"""
        return hashlib.sha256(url.encode()).hexdigest()[:12]

    @staticmethod
    def _short_id_to_url(short_id: str) -> str | None:
        """Extract URL from short_id. Returns None if not a valid new-url playlist ID."""
        # Format: synthetic-new-url-{hash}
        # We can't reverse the hash, so we need to look it up
        # This is handled by get_dynamic_playlist_by_id which queries all new URLs
        return None

    @staticmethod
    def _normalize_url(url: str) -> str:
        """
        Normalize a URL by:
        1. Removing query parameters and fragments
        2. Replacing path segments that look like IDs with placeholders

        This groups:
        - /billing?id=1 and /billing?id=2 -> /billing
        - /project/1/settings and /project/2/settings -> /project/{id}/settings
        - /user/abc-123-def/profile -> /user/{uuid}/profile
        - /item/xYz123AbC456DeF789 -> /item/{hash}
        """
        try:
            parsed = urlparse(url)
            path = parsed.path

            # Split path into segments
            segments = path.split("/")
            normalized_segments: list[str] = []

            for segment in segments:
                if not segment:  # Empty segment (leading/trailing slash)
                    normalized_segments.append(segment)
                # Check if segment looks like a UUID (standard format)
                elif re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", segment, re.I):
                    normalized_segments.append("{uuid}")
                # Check if segment is purely numeric (likely an ID)
                elif re.match(r"^\d+$", segment):
                    normalized_segments.append("{id}")
                # Check if segment is a long alphanumeric string (likely hash/encoded ID)
                # Must be at least 16 chars to avoid false positives with normal words
                elif re.match(r"^[a-z0-9_-]{16,}$", segment, re.I):
                    normalized_segments.append("{hash}")
                else:
                    # Keep segment as-is
                    normalized_segments.append(segment)

            normalized_path = "/".join(normalized_segments)
            normalized = f"{parsed.scheme}://{parsed.netloc}{normalized_path}"

            # Remove trailing slash for consistency (except for root path)
            if normalized.endswith("/") and len(normalized_path) > 1:
                normalized = normalized.rstrip("/")

            return normalized
        except Exception:
            # If URL parsing fails, return original URL
            return url

    @staticmethod
    def _get_new_urls_with_sessions(team: Team) -> tuple[dict[str, int], dict[str, list[str]]]:
        """
        Query ClickHouse to find URL patterns that first appeared in the last 14 days.
        Pre-computes BOTH session counts AND session IDs for each pattern in a SINGLE query.

        Returns: tuple of (pattern -> count dict, pattern -> session_ids list dict)
        """
        cache_key = f"{NewUrlsSyntheticPlaylistSource.CACHE_KEY_PREFIX}_with_sessions_{team.pk}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        now = datetime.now(UTC)
        lookback_start = now - timedelta(days=NewUrlsSyntheticPlaylistSource.LOOKBACK_DAYS)
        history_window_start = now - timedelta(days=90)

        # Fetch URLs from last 90 days for pattern detection
        # AND from last 14 days for counting (we'll do both in one pass)
        query = """
            SELECT
                session_id,
                arrayJoin(all_urls) as url,
                min(min_first_timestamp) as first_seen
            FROM session_replay_events
            WHERE team_id = %(team_id)s
                AND min_first_timestamp >= %(history_start)s
                AND url != ''
            GROUP BY session_id, url
            ORDER BY first_seen DESC
            LIMIT 50000
        """

        result = sync_execute(
            query,
            {
                "team_id": team.pk,
                "history_start": history_window_start,
            },
        )

        # Build pattern tracking data structures
        pattern_first_seen: dict[str, datetime] = {}
        pattern_sessions: dict[str, set[str]] = {}  # pattern -> set of session_ids

        for session_id, raw_url, first_seen_ts in result:
            normalized = NewUrlsSyntheticPlaylistSource._normalize_url(raw_url)

            # Track earliest appearance of this pattern
            if normalized not in pattern_first_seen or first_seen_ts < pattern_first_seen[normalized]:
                pattern_first_seen[normalized] = first_seen_ts

            # Track sessions for patterns in the lookback window (for counting)
            if lookback_start <= first_seen_ts <= now:
                if normalized not in pattern_sessions:
                    pattern_sessions[normalized] = set()
                pattern_sessions[normalized].add(session_id)

        # Filter to patterns that FIRST appeared within the lookback window
        new_patterns_with_counts = {
            pattern: len(pattern_sessions.get(pattern, set()))
            for pattern, first_seen in pattern_first_seen.items()
            if lookback_start <= first_seen <= now
        }

        # Sort by count (descending) then by pattern name, take top 20
        sorted_patterns = sorted(
            new_patterns_with_counts.items(),
            key=lambda x: (-x[1], x[0]),  # Sort by count desc, then pattern asc
        )[:20]

        counts_dict = dict(sorted_patterns)

        # Also prepare session IDs for the top patterns (convert sets to sorted lists)
        sessions_dict = {pattern: sorted(pattern_sessions.get(pattern, set())) for pattern in counts_dict.keys()}

        result_tuple = (counts_dict, sessions_dict)
        cache.set(cache_key, result_tuple, NewUrlsSyntheticPlaylistSource.CACHE_TTL)
        return result_tuple

    @staticmethod
    def _get_new_urls_with_counts(team: Team) -> dict[str, int]:
        """
        Query ClickHouse to find URL patterns that first appeared in the last 14 days.
        Also pre-computes session counts for each pattern in a SINGLE query for performance.

        Returns: dict mapping pattern -> session count
        """
        counts_dict, _ = NewUrlsSyntheticPlaylistSource._get_new_urls_with_sessions(team)
        return counts_dict

    @staticmethod
    def _get_new_urls(team: Team) -> list[str]:
        """
        Get just the list of new URL patterns (for backwards compatibility).
        """
        return list(NewUrlsSyntheticPlaylistSource._get_new_urls_with_counts(team).keys())

    def get_session_ids(self, team: Team, user: User, limit: int | None = None, offset: int | None = None) -> list[str]:
        """
        Get session IDs for sessions that visited URLs matching this pattern.
        Uses pre-computed session IDs from _get_new_urls_with_sessions for performance.
        """
        if not self.url:
            return []

        # Get pre-computed session IDs (cached for 1 hour)
        _, sessions_dict = self._get_new_urls_with_sessions(team)

        # Look up session IDs for this pattern
        session_ids = sessions_dict.get(self.url, [])

        return self._paginate_list(session_ids, limit, offset)

    def count_session_ids(self, team: Team, user: User) -> int:
        """
        Count sessions that visited URLs matching this pattern.
        Uses pre-computed counts from _get_new_urls_with_counts for performance.
        """
        if not self.url:
            return 0

        # Try to get the pre-computed count first (fast path)
        counts_dict = self._get_new_urls_with_counts(team)
        if self.url in counts_dict:
            return counts_dict[self.url]

        # Fallback: if not in pre-computed cache, use the expensive query
        # (This shouldn't happen in normal operation)
        all_session_ids = self.get_session_ids(team, user, limit=None, offset=None)
        return len(all_session_ids)

    def generate_dynamic_playlists(self, team: Team) -> list["SyntheticPlaylistDefinition"]:
        """Generate a playlist for each new URL"""
        new_urls = self._get_new_urls(team)
        playlists = []

        for idx, url in enumerate(new_urls):
            # Create a source instance for this specific URL
            url_source = NewUrlsSyntheticPlaylistSource(url=url)
            url_hash = self._url_to_hash(url)
            short_id = f"synthetic-new-url-{url_hash}"

            # Truncate URL for display if too long
            display_url = url if len(url) <= 60 else url[:57] + "..."

            playlists.append(
                SyntheticPlaylistDefinition(
                    id=self.MIN_ID - idx,  # Negative IDs to avoid conflicts
                    short_id=short_id,
                    name=f"New URL: {display_url}",
                    description=f"Recordings from the last {self.LOOKBACK_DAYS} days on a page not previously seen within the last 90 days",
                    type="collection",
                    get_session_ids=url_source.get_session_ids,
                    count_session_ids=url_source.count_session_ids,
                    metadata={"icon": "IconSparkles", "is_user_specific": False, "url": url},
                )
            )

        return playlists

    def get_dynamic_playlist_by_id(self, short_id: str, team: Team) -> "SyntheticPlaylistDefinition | None":
        """Retrieve a specific new URL playlist by its short_id"""
        if not short_id.startswith("synthetic-new-url-"):
            return None

        # Extract hash from short_id
        url_hash = short_id.replace("synthetic-new-url-", "")

        # Get all new URLs and find the one matching this hash
        new_urls = self._get_new_urls(team)
        for url in new_urls:
            if self._url_to_hash(url) == url_hash:
                # Create a source instance for this specific URL
                url_source = NewUrlsSyntheticPlaylistSource(url=url)
                display_url = url if len(url) <= 60 else url[:57] + "..."

                return SyntheticPlaylistDefinition(
                    id=self.MIN_ID,  # Use a consistent ID for individual lookups
                    short_id=short_id,
                    name=f"New URL: {display_url}",
                    description=f"Recordings from the last {self.LOOKBACK_DAYS} days on a page not previously seen within the last 90 days",
                    type="collection",
                    get_session_ids=url_source.get_session_ids,
                    count_session_ids=url_source.count_session_ids,
                    metadata={"icon": "IconSparkles", "is_user_specific": False, "url": url},
                )

        return None


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
    ]

    # Only add summarised playlist if EE is available
    if HAS_EE:
        playlists.append(SummarisedPlaylistSource().to_synthetic_playlist())

    # Filter out None values (sources that only generate dynamic playlists)
    return [p for p in playlists if p is not None]


# Registry of dynamic synthetic playlist sources
def _get_dynamic_synthetic_playlist_sources() -> list[SyntheticPlaylistSource]:
    return [
        NewUrlsSyntheticPlaylistSource(),
    ]


# fixed list of synthetic playlists, including Watch History, Expiring Soon, etc
SYNTHETIC_PLAYLISTS: list[SyntheticPlaylistDefinition] = _get_static_synthetic_playlists()
# dynamic synthetic playlists, detecting newly seen URLs
DYNAMIC_SYNTHETIC_PLAYLIST_SOURCES: list[SyntheticPlaylistSource] = _get_dynamic_synthetic_playlist_sources()


def get_synthetic_playlist(short_id: str, team: Team | None = None) -> SyntheticPlaylistDefinition | None:
    """
    Get a synthetic playlist by short_id.
    Checks both static playlists and dynamic playlists (if team is provided).
    """
    # Check static playlists first
    for playlist in SYNTHETIC_PLAYLISTS:
        if playlist.short_id == short_id:
            return playlist

    # Check dynamic playlists if team is provided
    if team:
        for source in DYNAMIC_SYNTHETIC_PLAYLIST_SOURCES:
            # Gate new URL collections behind feature flag
            if isinstance(source, NewUrlsSyntheticPlaylistSource):
                try:
                    flag_result = posthoganalytics.get_feature_flag(
                        "replay-new-detected-url-collections",
                        str(team.uuid),
                        groups={"organization": str(team.organization_id)},
                    )
                    # Skip if flag is not set to "test" variant
                    if flag_result is None or flag_result != "test":  # type: ignore[comparison-overlap]
                        continue
                except Exception:
                    # If feature flag check fails, skip this source
                    continue

            dynamic_playlist = source.get_dynamic_playlist_by_id(short_id, team)
            if dynamic_playlist:
                return dynamic_playlist

    return None


def get_all_synthetic_playlists(team: Team) -> list[SyntheticPlaylistDefinition]:
    """
    Get all synthetic playlists for a team, including both static and dynamic ones.
    """
    all_playlists = list(SYNTHETIC_PLAYLISTS)
    # Add dynamic playlists from each source
    for source in DYNAMIC_SYNTHETIC_PLAYLIST_SOURCES:
        # Gate new URL collections behind feature flag
        if isinstance(source, NewUrlsSyntheticPlaylistSource):
            try:
                flag_result = posthoganalytics.get_feature_flag(
                    "replay-new-detected-url-collections",
                    str(team.uuid),
                    groups={"organization": str(team.organization_id)},
                )
                if flag_result is None or flag_result != "test":  # type: ignore[comparison-overlap]
                    continue
            except Exception:
                # If feature flag check fails, skip this source
                continue

        all_playlists.extend(source.generate_dynamic_playlists(team))

    return all_playlists
