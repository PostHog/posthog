from dataclasses import dataclass


@dataclass(frozen=True)
class PlaylistToCount:
    playlist_id: int


@dataclass(frozen=True)
class CountPlaylistInput:
    playlist_id: int
