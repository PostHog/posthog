from dataclasses import dataclass, field
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField


@dataclass
class TMDbEndpointConfig:
    name: str
    path: str
    # Key in the JSON response holding the list of rows. "results" for the paginated list/trending
    # endpoints, "genres" for the genre lists, and None when the response body is itself a bare list
    # (the configuration languages/countries endpoints).
    data_key: Optional[str] = "results"
    # Paginated endpoints expose `page` / `total_pages` and accept a `page` query param. The reference
    # endpoints (genres, languages, countries) return everything in a single response.
    paginated: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # No TMDB v3 list endpoint exposes a server-side updated-after filter, so every endpoint is full
    # refresh only. Kept for parity with other sources and in case the changes API is wired up later.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


TMDB_ENDPOINTS: dict[str, TMDbEndpointConfig] = {
    # Movies
    "movie_popular": TMDbEndpointConfig(name="movie_popular", path="/movie/popular"),
    "movie_top_rated": TMDbEndpointConfig(name="movie_top_rated", path="/movie/top_rated"),
    "movie_now_playing": TMDbEndpointConfig(name="movie_now_playing", path="/movie/now_playing"),
    "movie_upcoming": TMDbEndpointConfig(name="movie_upcoming", path="/movie/upcoming"),
    # TV
    "tv_popular": TMDbEndpointConfig(name="tv_popular", path="/tv/popular"),
    "tv_top_rated": TMDbEndpointConfig(name="tv_top_rated", path="/tv/top_rated"),
    "tv_on_the_air": TMDbEndpointConfig(name="tv_on_the_air", path="/tv/on_the_air"),
    "tv_airing_today": TMDbEndpointConfig(name="tv_airing_today", path="/tv/airing_today"),
    # People
    "person_popular": TMDbEndpointConfig(name="person_popular", path="/person/popular"),
    # Trending (daily window)
    "trending_movies": TMDbEndpointConfig(name="trending_movies", path="/trending/movie/day"),
    "trending_tv": TMDbEndpointConfig(name="trending_tv", path="/trending/tv/day"),
    "trending_people": TMDbEndpointConfig(name="trending_people", path="/trending/person/day"),
    # Reference data — single response, no pagination
    "movie_genres": TMDbEndpointConfig(
        name="movie_genres", path="/genre/movie/list", data_key="genres", paginated=False
    ),
    "tv_genres": TMDbEndpointConfig(name="tv_genres", path="/genre/tv/list", data_key="genres", paginated=False),
    "languages": TMDbEndpointConfig(
        name="languages",
        path="/configuration/languages",
        data_key=None,
        paginated=False,
        primary_keys=["iso_639_1"],
    ),
    "countries": TMDbEndpointConfig(
        name="countries",
        path="/configuration/countries",
        data_key=None,
        paginated=False,
        primary_keys=["iso_3166_1"],
    ),
}

ENDPOINTS = tuple(TMDB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TMDB_ENDPOINTS.items()
}
