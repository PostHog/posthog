import re
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Literal, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.github.settings import GITHUB_ENDPOINTS, GithubEndpointConfig

GITHUB_BASE_URL = "https://api.github.com"


class GithubRetryableError(Exception):
    pass


@dataclasses.dataclass
class GithubResumeConfig:
    next_url: str


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for GitHub API filters."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return str(value)


def _build_initial_params(
    config: GithubEndpointConfig,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    # workflow_runs has a different param surface: it accepts neither
    # state/sort/direction nor `since`, and always returns newest-first by
    # created_at. We intentionally send no time filter either — its `created`
    # filter would cap the result set to GitHub's 1,000-result search limit and
    # silently drop rows on busy repos. Incremental sync is handled instead by
    # paginating newest-first and stopping at the cursor (see get_rows), so the
    # request stays a plain paged read regardless of incremental state.
    if endpoint == "workflow_runs":
        return {"per_page": config.page_size}

    params: dict[str, Any] = {
        "per_page": config.page_size,
        "state": "all",
        # Default to created asc — created is immutable, so new items append
        # to the end and don't shift already-fetched pages.
        "sort": "created",
        "direction": "asc",
    }

    if should_use_incremental_field and db_incremental_field_last_value:
        formatted_value = _format_incremental_value(db_incremental_field_last_value)
        incremental = incremental_field or config.default_incremental_field or "updated_at"
        sort_field_mapping = {
            "updated_at": "updated",
            "created_at": "created",
        }
        if incremental not in sort_field_mapping:
            raise ValueError(
                f"Unsupported GitHub incremental field '{incremental}'. Expected one of: {sorted(sort_field_mapping)}."
            )
        params["sort"] = sort_field_mapping[incremental]
        params["direction"] = config.sort_mode
        if endpoint in ("issues", "commits"):
            params["since"] = formatted_value

    return params


def _build_initial_url(config: GithubEndpointConfig, repository: str, params: dict[str, Any]) -> str:
    path = config.path.format(repository=repository)
    if not params:
        return f"{GITHUB_BASE_URL}{path}"
    return f"{GITHUB_BASE_URL}{path}?{urlencode(params)}"


def _resolve_sort_mode(
    config: GithubEndpointConfig,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Literal["asc", "desc"]:
    """The order rows are actually emitted in. SourceResponse.sort_mode must
    match this, otherwise the pipeline persists the cursor watermark assuming
    the wrong direction (e.g. advancing past unread older rows).

    Most endpoints emit asc on the first sync / full refresh (stable offset
    pagination via sort=created&direction=asc) and only flip to their
    configured sort once a cutoff exists. workflow_runs is different: it ignores
    sort/direction and always returns newest-first, so it emits desc on every
    sync — including the first. workflow_jobs inherits that order: it fans out
    over workflow_runs newest-first, so its jobs land newest-first too.
    """
    if endpoint in ("workflow_runs", "workflow_jobs"):
        return config.sort_mode
    if should_use_incremental_field and db_incremental_field_last_value:
        return config.sort_mode
    return "asc"


def _get_headers(access_token: str, endpoint: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Stargazers needs this Accept header to include the starred_at timestamp.
    if endpoint == "stargazers":
        headers["Accept"] = "application/vnd.github.star+json"
    return headers


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with rel="next" from GitHub's Link header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def _as_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC so tz-aware values (GitHub returns ISO 8601
    with `Z`) can be safely compared against naive cutoffs from the DB."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _is_older_than_cutoff(value: Any, cutoff: datetime) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        try:
            parsed_value = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return False
    elif isinstance(value, datetime):
        parsed_value = value
    else:
        return False
    return _as_utc(parsed_value) <= _as_utc(cutoff)


def _should_stop_desc(
    data: list[dict[str, Any]],
    sort_mode: str,
    incremental_field: str | None,
    cutoff: Any,
) -> bool:
    """Desc + incremental can stop the moment we see the first old record."""
    if sort_mode != "desc" or not incremental_field or not cutoff or not data:
        return False
    if not isinstance(cutoff, datetime):
        return False
    return any(_is_older_than_cutoff(item.get(incremental_field), cutoff) for item in data if item)


def validate_credentials(personal_access_token: str, repository: str) -> tuple[bool, str | None]:
    """Validate GitHub API credentials by making a test request to the repository."""
    url = f"{GITHUB_BASE_URL}/repos/{repository}"
    headers = {
        "Authorization": f"Bearer {personal_access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = make_tracked_session().get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return True, None

        if response.status_code == 401:
            return False, "Invalid personal access token"

        if response.status_code == 404:
            return False, f"Repository '{repository}' not found or not accessible"

        try:
            error_data = response.json()
            message = error_data.get("message", response.text)
            return False, message
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _flatten_commit(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten commit data by extracting nested author/committer info."""
    if "commit" in item and isinstance(item["commit"], dict):
        commit_data = item["commit"]
        item["message"] = commit_data.get("message")

        if "author" in commit_data and isinstance(commit_data["author"], dict):
            item["author_name"] = commit_data["author"].get("name")
            item["author_email"] = commit_data["author"].get("email")
            item["created_at"] = commit_data["author"].get("date")

        if "committer" in commit_data and isinstance(commit_data["committer"], dict):
            item["committer_name"] = commit_data["committer"].get("name")
            item["committer_email"] = commit_data["committer"].get("email")
            item["committed_at"] = commit_data["committer"].get("date")

    if "author" in item and isinstance(item["author"], dict):
        item["author_id"] = item["author"].get("id")
        item["author_login"] = item["author"].get("login")

    if "committer" in item and isinstance(item["committer"], dict):
        item["committer_id"] = item["committer"].get("id")
        item["committer_login"] = item["committer"].get("login")

    return item


def _flatten_stargazer(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten stargazer data when using starred_at timestamp."""
    if "user" in item and isinstance(item["user"], dict):
        user = item.pop("user")
        item["id"] = user["id"]
        item["login"] = user.get("login")
        item["avatar_url"] = user.get("avatar_url")
        item["type"] = user.get("type")
    return item


def _is_issue_not_pr(item: dict[str, Any]) -> bool:
    """Exclude pull requests from the issues endpoint.

    GitHub's Issues API returns both issues and PRs. PRs can be identified
    by the presence of the 'pull_request' key in the response.
    """
    return "pull_request" not in item or item["pull_request"] is None


def _get_item_mapper(endpoint: str) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if endpoint == "commits":
        return _flatten_commit
    if endpoint == "stargazers":
        return _flatten_stargazer
    return None


def _get_item_filter(endpoint: str) -> Callable[[dict[str, Any]], bool] | None:
    if endpoint == "issues":
        return _is_issue_not_pr
    return None


@retry(
    retry=retry_if_exception_type((GithubRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(page_url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> requests.Response:
    response = make_tracked_session().get(page_url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise GithubRetryableError(f"Github API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        logger.error(f"Github API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response


def _iter_pages(
    url: str,
    headers: dict[str, str],
    response_data_path: str | None,
    logger: FilteringBoundLogger,
    max_pages: int | None = None,
    page_cap_context: dict[str, Any] | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str, str | None]]:
    """Yield (items, page_url, next_url) for each page of a paginated GitHub list,
    unwrapping the envelope and following the Link header. Stops at ``max_pages``,
    logging a structured warning when the cap is reached. An empty or ``null``
    envelope body simply ends iteration — there is nothing to truncate."""
    page_count = 0
    while True:
        response = _fetch_page(url, headers, logger)
        data = response.json()
        if response_data_path and isinstance(data, dict):
            data = data.get(response_data_path) or []
        if not isinstance(data, list) or not data:
            return
        next_url = _parse_next_url(response.headers.get("Link", ""))
        yield data, url, next_url
        page_count += 1
        if not next_url:
            return
        if max_pages is not None and page_count >= max_pages:
            logger.warning(
                "Github: per-parent page cap reached; remaining pages skipped",
                max_pages=max_pages,
                **(page_cap_context or {}),
            )
            return
        url = next_url


def _iter_jobs_for_run(
    repository: str,
    run_id: Any,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: GithubEndpointConfig,
) -> Iterator[dict[str, Any]]:
    path = config.path.format(repository=repository, run_id=run_id)
    params: dict[str, Any] = {"per_page": config.page_size, **(config.extra_params or {})}
    url = f"{GITHUB_BASE_URL}{path}?{urlencode(params)}"
    for jobs, _page_url, _next_url in _iter_pages(
        url,
        headers,
        config.response_data_path,
        logger,
        max_pages=config.max_pages_per_parent,
        page_cap_context={"repository": repository, "run_id": run_id},
    ):
        yield from jobs


def _fan_out_get_rows(
    personal_access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[Any]:
    """Single-hop parent->child fan-out: walk the parent endpoint newest-first and
    emit every child row for each parent. Incremental bounding happens on the
    parent's created_at cursor (the same desc early-stop workflow_runs uses);
    children upsert by primary key, so re-reading a boundary parent is harmless.

    The child cursor value (max job created_at) is compared against the parent's
    created_at — they coincide closely since a job is created when its run starts,
    so the watermark sits slightly above the newest run's timestamp. Re-reading a
    boundary parent is harmless (jobs upsert by id), but note the inverse: a run
    that was in_progress when first synced drops below the watermark once it
    finishes, so its terminal job conclusions and any later-added jobs are not
    re-fetched. This is the same created_at-cursor staleness workflow_runs carries;
    the workflow_run webhook (followup) is the fix, not re-scanning history.
    """
    child_config = GITHUB_ENDPOINTS[endpoint]
    assert child_config.fan_out_parent is not None  # guarded by the get_rows dispatch
    parent_config = GITHUB_ENDPOINTS[child_config.fan_out_parent]
    headers = _get_headers(personal_access_token, endpoint)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    parent_field = incremental_field or parent_config.default_incremental_field or "created_at"
    parent_cutoff = db_incremental_field_last_value if should_use_incremental_field else None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        parent_url: str = resume_config.next_url
        logger.debug(f"Github: resuming {endpoint} fan-out from parent URL: {parent_url}")
    else:
        parent_url = _build_initial_url(parent_config, repository, {"per_page": parent_config.page_size})

    for runs, page_url, _next_url in _iter_pages(parent_url, headers, parent_config.response_data_path, logger):
        stop_after_this_page = _should_stop_desc(runs, "desc", parent_field, parent_cutoff)

        for run in runs:
            run_id = run.get("id")
            if run_id is None:
                continue
            # Only fan out parents at/above the watermark; older ones were synced before.
            if parent_cutoff is not None and _is_older_than_cutoff(run.get(parent_field), parent_cutoff):
                continue
            for job in _iter_jobs_for_run(repository, run_id, headers, logger, child_config):
                batcher.batch(job)
                if batcher.should_yield():
                    yield batcher.get_table()
                    # Checkpoint the parent page; resume re-fans it out and dedupes by id.
                    if not stop_after_this_page:
                        resumable_source_manager.save_state(GithubResumeConfig(next_url=page_url))

        if stop_after_this_page:
            break

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def get_rows(
    personal_access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = GITHUB_ENDPOINTS[endpoint]
    if config.fan_out_parent is not None:
        yield from _fan_out_get_rows(
            personal_access_token=personal_access_token,
            repository=repository,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        )
        return

    headers = _get_headers(personal_access_token, endpoint)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    actual_sort_mode = _resolve_sort_mode(
        config, endpoint, should_use_incremental_field, db_incremental_field_last_value
    )

    stop_field: str | None = None
    stop_cutoff: Any = None
    if actual_sort_mode == "desc" and should_use_incremental_field:
        stop_field = incremental_field or config.default_incremental_field
        stop_cutoff = db_incremental_field_last_value

    item_filter = _get_item_filter(endpoint)
    item_mapper = _get_item_mapper(endpoint)

    initial_params = _build_initial_params(
        config, endpoint, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Github: resuming from URL: {url}")
    else:
        url = _build_initial_url(config, repository, initial_params)

    while True:
        response = _fetch_page(url, headers, logger)

        data = response.json()
        # Most GitHub list endpoints return a JSON array at the top level,
        # but some (e.g. /actions/runs) wrap results in {"<resource>": [...]}.
        if config.response_data_path and isinstance(data, dict):
            data = data.get(config.response_data_path, [])
        if not isinstance(data, list) or not data:
            break

        next_url = _parse_next_url(response.headers.get("Link", ""))
        stop_after_this_page = _should_stop_desc(data, actual_sort_mode, stop_field, stop_cutoff)

        # Chunk boundaries don't align with page boundaries (issues drops
        # PRs, items can also straddle the chunk_size cap), so checkpoint
        # the CURRENT page URL. On resume we re-fetch the current page and
        # rely on primary_keys merge semantics to dedupe already-yielded
        # items; this avoids silently dropping items that were batched but
        # not yet yielded when the worker restarts.
        checkpoint_url = url

        for item in data:
            if item_filter and not item_filter(item):
                continue
            if item_mapper:
                item = item_mapper(item)
            batcher.batch(item)

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table

                if not stop_after_this_page:
                    resumable_source_manager.save_state(GithubResumeConfig(next_url=checkpoint_url))

        if stop_after_this_page or not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def github_source(
    personal_access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = GITHUB_ENDPOINTS[endpoint]

    actual_sort_mode = _resolve_sort_mode(
        endpoint_config, endpoint, should_use_incremental_field, db_incremental_field_last_value
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            personal_access_token=personal_access_token,
            repository=repository,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[endpoint_config.primary_key],
        sort_mode=actual_sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
