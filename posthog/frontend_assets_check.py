import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from pathlib import Path

from django.conf import settings

import requests
from prometheus_client import Counter
from structlog import get_logger

from posthog.stable_chunks import _resolve_stable_chunks
from posthog.utils import _resolve_entry_assets

logger = get_logger(__name__)

FRONTEND_DIST = Path(settings.BASE_DIR) / "frontend" / "dist"
# The content-hash suffix the frontend build writes, which the CDN upload also uses to mark files immutable.
HASHED_FILE = re.compile(r"[\w.-]+-[A-Z0-9]{6,}\.(?:js|css|json|wasm)")
# CloudFront caches a missing object for 10 seconds, so a retry sooner than that sees the same miss.
RETRY_DELAYS_SECONDS = (15, 30)

FRONTEND_ASSETS_CHECK = Counter(
    "posthog_frontend_assets_check",
    "Startup checks that the files this image's pages load exist on JS_URL",
    labelnames=["result"],
)


class AssetStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    UNREACHABLE = "unreachable"


def html_referenced_files(dist_dir: Path) -> set[str]:
    """Paths relative to JS_URL that the built HTML names literally: entries, chunk maps and workers."""
    names: set[str] = set()
    for page in dist_dir.glob("*.html"):
        names.update(HASHED_FILE.findall(page.read_text()))
    return {f"static/{name}" for name in names}


def boot_files() -> list[str]:
    """Paths relative to JS_URL that a page loads before it renders, on both the hashed and the stable build."""
    css, preload_js, font = _resolve_entry_assets(include_authenticated_shell=True)
    files = html_referenced_files(FRONTEND_DIST) | set(preload_js) | {path for path in (css, font) if path}
    stable_chunks = _resolve_stable_chunks()
    if stable_chunks is not None:
        files |= set(stable_chunks.preload_urls(include_authenticated_shell=True))
        files |= set(stable_chunks.eager_css_urls)
    return sorted(files)


def probe_assets(base_url: str, paths: list[str], session: requests.Session) -> dict[str, AssetStatus]:
    def probe(path: str) -> AssetStatus:
        try:
            response = session.head(f"{base_url}/{path}", timeout=5, allow_redirects=True)
        except requests.RequestException:
            return AssetStatus.UNREACHABLE
        if response.ok:
            return AssetStatus.OK
        # Every JS_URL CDN answers 404 for an object the bucket lacks. A 403 means an access problem,
        # such as a WAF block or broken origin access, and a 5xx or timeout says nothing about the file.
        if response.status_code == 404:
            return AssetStatus.MISSING
        return AssetStatus.UNREACHABLE

    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(paths, pool.map(probe, paths)))


def check_result(statuses: dict[str, AssetStatus]) -> str:
    values = set(statuses.values())
    if AssetStatus.MISSING in values:
        return "missing"
    if AssetStatus.UNREACHABLE in values:
        return "unreachable"
    return "ok"


def _report_frontend_assets() -> None:
    try:
        _check_and_report()
    except Exception:
        FRONTEND_ASSETS_CHECK.labels(result="error").inc()
        logger.exception("frontend_assets_check_error")


def _check_and_report() -> None:
    files = boot_files()
    if not files:
        FRONTEND_ASSETS_CHECK.labels(result="no_references").inc()
        logger.warning("frontend_assets_check_no_references", dist_dir=str(FRONTEND_DIST))
        return

    with requests.Session() as session:
        statuses = probe_assets(settings.JS_URL, files, session)
        for delay in RETRY_DELAYS_SECONDS:
            missing = [path for path, status in statuses.items() if status == AssetStatus.MISSING]
            if not missing:
                break
            time.sleep(delay)
            statuses |= probe_assets(settings.JS_URL, missing, session)

    result = check_result(statuses)
    FRONTEND_ASSETS_CHECK.labels(result=result).inc()
    log = logger.info if result == "ok" else logger.warning
    log(
        "frontend_assets_check",
        result=result,
        js_url=settings.JS_URL,
        checked=len(files),
        missing=[path for path, status in statuses.items() if status == AssetStatus.MISSING],
        unreachable=[path for path, status in statuses.items() if status == AssetStatus.UNREACHABLE],
    )


_started = False
_started_lock = threading.Lock()


def start_frontend_assets_check() -> None:
    """Report, once per process, whether the CDN serves every file this image's pages load at boot.

    It only logs and counts, and never changes readiness.
    """
    global _started
    if settings.DEBUG or settings.TEST or not settings.JS_URL:
        return
    with _started_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_report_frontend_assets, name="frontend-assets-check", daemon=True).start()
