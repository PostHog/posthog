"""Authenticate to internal Metabase via SSO and cache the session cookie.

Production Metabase sits behind ALB Cognito OAuth, so callers need both the
ALB session cookies (`ph_int_auth-0`, `ph_int_auth-1`) and the Metabase
application cookies (`metabase.SESSION`, `metabase.DEVICE`). API keys alone
won't pass the ALB.

Workflow:
    hogli metabase:login [--region us|eu]   # opens system browser, captures cookies
    hogli metabase:cookie [--region us|eu]  # prints cached cookie header

Scripts can then use:
    METABASE_COOKIE="$(hogli metabase:cookie --region us)" curl ...

Cookies are cached at ~/.config/posthog/metabase/cookie-{region} with mode 0600.
"""

from __future__ import annotations

import time
import webbrowser
from pathlib import Path

import click
from hogli.core.cli import cli

LOGIN_TIMEOUT_SECONDS: float = 180.0
LOGIN_POLL_INTERVAL_SECONDS: float = 1.0
# Chrome buffers cookies in memory and flushes to SQLite roughly every 30s.
# After this many seconds without progress we hint at closing the tab to
# force a flush.
FLUSH_HINT_AFTER_SECONDS: float = 8.0

# Per-browser profile-cookie locations. Each entry is (loader_name, base_directory).
# We glob `<base>/*/Cookies` to discover every profile (Default, Profile 1, ...).
_HOME = Path.home()
_CHROMIUM_PROFILE_ROOTS: dict[str, list[Path]] = {
    "chrome": [_HOME / "Library/Application Support/Google/Chrome"],
    "chromium": [_HOME / "Library/Application Support/Chromium"],
    "brave": [_HOME / "Library/Application Support/BraveSoftware/Brave-Browser"],
}

REGIONS: dict[str, str] = {
    "us": "metabase.prod-us.posthog.dev",
    "eu": "metabase.prod-eu.posthog.dev",
}
REQUIRED_COOKIES: tuple[str, ...] = (
    "metabase.SESSION",
    "metabase.DEVICE",
    "ph_int_auth-0",
    "ph_int_auth-1",
)
SUPPORTED_BROWSERS: tuple[str, ...] = ("chrome", "chromium", "brave", "firefox", "safari")
CACHE_DIR: Path = Path.home() / ".config" / "posthog" / "metabase"


def _cookie_path(region: str) -> Path:
    return CACHE_DIR / f"cookie-{region}"


def _format_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _enumerate_cookie_files(browser: str | None) -> list[tuple[str, Path]]:
    """Return (loader_name, cookie_file_path) pairs for every browser profile to try.

    Chromium-family browsers (Chrome, Brave, Chromium) keep a `Cookies`
    SQLite db per profile (`Default`, `Profile 1`, ...). We glob each profile
    directory so users with multiple profiles (work + personal) don't have to
    care which one they logged in with.

    Firefox and Safari fall back to the default `browser_cookie3` loader.
    """
    targets: list[tuple[str, Path]] = []
    selected = SUPPORTED_BROWSERS if browser is None else (browser,)
    for name in selected:
        if name in _CHROMIUM_PROFILE_ROOTS:
            for root in _CHROMIUM_PROFILE_ROOTS[name]:
                if not root.exists():
                    continue
                for cookies_db in sorted(root.glob("*/Cookies")):
                    targets.append((name, cookies_db))
        else:
            targets.append((name, Path()))
    return targets


def _load_cookies_from_browser(domain: str, browser: str | None) -> dict[str, str]:
    """Read cookies for `domain` from the user's system browser cookie store.

    Decrypting Chromium cookies on macOS triggers a one-time Keychain prompt
    per profile; users who pick "Always allow" won't see it again.
    """
    try:
        import browser_cookie3
    except ImportError as exc:
        raise click.ClickException(
            "browser-cookie3 is not installed. Run `uv sync` to install dev dependencies.",
        ) from exc

    if browser is not None and browser not in SUPPORTED_BROWSERS:
        raise click.ClickException(f"Unsupported browser: {browser}")

    targets = _enumerate_cookie_files(browser)
    found: dict[str, str] = {}
    errors: list[str] = []
    for loader_name, cookie_file in targets:
        loader = getattr(browser_cookie3, loader_name, None)
        if loader is None:
            continue
        kwargs: dict = {"domain_name": domain}
        if cookie_file != Path():
            kwargs["cookie_file"] = str(cookie_file)
        try:
            jar = loader(**kwargs)
        except Exception as exc:
            errors.append(f"{loader_name} ({cookie_file or 'default'}): {exc}")
            continue
        for cookie in jar:
            if cookie.name in REQUIRED_COOKIES and cookie.value:
                found[cookie.name] = cookie.value

    if not found and errors:
        click.echo("\n".join(f"  warn: {e}" for e in errors), err=True)
    return found


def _write_cookie_file(region: str, cookie_header: str) -> Path:
    path = _cookie_path(region)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookie_header)
    path.chmod(0o600)
    return path


def _read_cookie_file(region: str) -> str | None:
    path = _cookie_path(region)
    if not path.exists():
        return None
    return path.read_text().strip()


def _check_cookie(domain: str, cookie_header: str, timeout: float = 5.0) -> bool:
    """Hit /api/user/current to confirm the cookie is still valid."""
    import requests

    try:
        response = requests.get(
            f"https://{domain}/api/user/current",
            headers={"Cookie": cookie_header},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException:
        return False
    return response.status_code == 200


def _wait_for_valid_cookie(
    domain: str,
    browser: str | None,
    timeout: float,
    interval: float,
) -> str:
    """Poll the browser cookie store until a valid Metabase session appears.

    Returns the cookie header on success. Raises `click.ClickException` after
    `timeout` seconds without finding a valid session.

    Chrome flushes cookies to its on-disk SQLite store roughly every 30s, so a
    freshly-set `metabase.SESSION` can be invisible to us for a while. After
    `FLUSH_HINT_AFTER_SECONDS` we surface a hint suggesting the user close the
    Metabase tab — closing a tab forces an immediate flush.
    """
    start = time.monotonic()
    deadline = start + timeout
    last_status = ""
    last_header: str | None = None
    flush_hint_shown = False
    while True:
        cookies = _load_cookies_from_browser(domain, browser)
        missing = [name for name in REQUIRED_COOKIES if name not in cookies]
        if not missing:
            cookie_header = _format_cookie_header(cookies)
            # Avoid pinging /api/user/current with the same header repeatedly
            # when the user already had a stale cookie set on disk.
            if cookie_header != last_header:
                last_header = cookie_header
                if _check_cookie(domain, cookie_header):
                    return cookie_header
                status = "Cookies present but session not yet valid; still waiting..."
            else:
                status = "Cookies present but session not yet valid; still waiting..."
        else:
            status = f"Waiting for cookies: missing {missing}..."

        if status != last_status:
            click.echo(status)
            last_status = status

        if not flush_hint_shown and time.monotonic() - start >= FLUSH_HINT_AFTER_SECONDS:
            click.echo(
                "  hint: if you've already signed in, close the Metabase tab — "
                "Chrome only flushes cookies to disk every ~30s, but closing a tab forces it.",
            )
            flush_hint_shown = True

        if time.monotonic() >= deadline:
            raise click.ClickException(
                f"Timed out after {timeout:.0f}s waiting for SSO. "
                "Make sure you completed login in the browser, or rerun with --browser to "
                "target a specific browser.",
            )
        time.sleep(interval)


def _login_region(region: str, browser: str | None, no_open: bool, timeout: float) -> None:
    """Authenticate one region: fast-path if already logged in, else open browser and wait."""
    domain = REGIONS[region]

    cookies = _load_cookies_from_browser(domain, browser)
    if all(name in cookies for name in REQUIRED_COOKIES):
        header = _format_cookie_header(cookies)
        if _check_cookie(domain, header):
            path = _write_cookie_file(region, header)
            click.echo(f"[{region}] already logged in; saved cookie to {path}")
            return

    if not no_open:
        click.echo(f"[{region}] opening https://{domain} in your default browser.")
        webbrowser.open(f"https://{domain}")
    click.echo(f"[{region}] complete SSO in the browser; capturing automatically when ready.")

    cookie_header = _wait_for_valid_cookie(domain, browser, timeout, LOGIN_POLL_INTERVAL_SECONDS)
    path = _write_cookie_file(region, cookie_header)
    click.echo(f"[{region}] saved cookie to {path}")


@cli.command(name="metabase:login", help="Log in to Metabase via SSO and cache the session cookie")
@click.option(
    "--region",
    type=click.Choice(sorted(REGIONS.keys())),
    required=True,
    help="Region to authenticate (one at a time, e.g. --region us or --region eu)",
)
@click.option(
    "--browser",
    type=click.Choice(SUPPORTED_BROWSERS),
    default=None,
    help="Read cookies from this browser only (default: scan all supported browsers)",
)
@click.option("--no-open", is_flag=True, help="Skip opening the browser; just capture cookies")
@click.option(
    "--timeout",
    type=float,
    default=LOGIN_TIMEOUT_SECONDS,
    show_default=True,
    help="Seconds to wait for SSO to complete before giving up",
)
def metabase_login(region: str, browser: str | None, no_open: bool, timeout: float) -> None:
    """Open Metabase in the default browser; capture cookies as soon as SSO completes.

    Already-valid sessions are fast-pathed (no browser tab opens),
    so re-running is cheap. Run once per region (us, eu).
    """
    _login_region(region, browser, no_open, timeout)


@cli.command(name="metabase:cookie", help="Print the cached Metabase cookie header")
@click.option(
    "--region",
    type=click.Choice(sorted(REGIONS.keys())),
    default="us",
    show_default=True,
)
@click.option("--check/--no-check", default=False, help="Validate the cookie before printing")
def metabase_cookie(region: str, check: bool) -> None:
    """Print the cached cookie header to stdout. Suitable for `METABASE_COOKIE=$(...)`."""
    cookie_header = _read_cookie_file(region)
    if cookie_header is None:
        raise click.ClickException(
            f"No cached cookie for region {region}. Run `hogli metabase:login --region {region}`.",
        )
    if check and not _check_cookie(REGIONS[region], cookie_header):
        raise click.ClickException(
            f"Cached cookie for {region} is no longer valid. Run `hogli metabase:login --region {region}` to refresh.",
        )
    # No trailing newline so $(hogli metabase:cookie) yields a clean header.
    click.echo(cookie_header, nl=False)
