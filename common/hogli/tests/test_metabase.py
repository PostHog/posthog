from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from unittest.mock import patch

import click
from click.testing import CliRunner
from hogli import metabase
from hogli.core.cli import cli


class _FakeCookie:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(metabase, "CACHE_DIR", tmp_path)
    yield tmp_path


def test_format_cookie_header_joins_with_semicolons() -> None:
    header = metabase._format_cookie_header({"a": "1", "b": "2"})
    assert header == "a=1; b=2"


def test_cookie_path_per_region(cache_dir: Path) -> None:
    assert metabase._cookie_path("us") == cache_dir / "cookie-us"
    assert metabase._cookie_path("eu") == cache_dir / "cookie-eu"


def test_write_cookie_file_is_owner_only(cache_dir: Path) -> None:
    path = metabase._write_cookie_file("us", "metabase.SESSION=abc")
    assert path.read_text() == "metabase.SESSION=abc"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_read_cookie_file_returns_none_when_missing(cache_dir: Path) -> None:
    assert metabase._read_cookie_file("us") is None


def test_read_cookie_file_strips_trailing_whitespace(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc\n")
    assert metabase._read_cookie_file("us") == "metabase.SESSION=abc"


def test_load_cookies_filters_to_required_names(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_jar = [
        _FakeCookie("metabase.SESSION", "s"),
        _FakeCookie("metabase.DEVICE", "d"),
        _FakeCookie("ph_int_auth-0", "a0"),
        _FakeCookie("ph_int_auth-1", "a1"),
        _FakeCookie("unrelated", "x"),
    ]

    class FakeBC3:
        @staticmethod
        def chrome(domain_name: str, cookie_file: str | None = None) -> list[_FakeCookie]:
            assert domain_name == "metabase.prod-us.posthog.dev"
            assert cookie_file == "/fake/profile/Cookies"
            return fake_jar

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    monkeypatch.setattr(
        metabase,
        "_enumerate_cookie_files",
        lambda browser: [("chrome", Path("/fake/profile/Cookies"))],
    )
    cookies = metabase._load_cookies_from_browser("metabase.prod-us.posthog.dev", "chrome")
    assert cookies == {
        "metabase.SESSION": "s",
        "metabase.DEVICE": "d",
        "ph_int_auth-0": "a0",
        "ph_int_auth-1": "a1",
    }


def test_enumerate_cookie_files_globs_chromium_profiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    chrome_root = tmp_path / "Chrome"
    (chrome_root / "Default").mkdir(parents=True)
    (chrome_root / "Default" / "Cookies").touch()
    (chrome_root / "Profile 1").mkdir()
    (chrome_root / "Profile 1" / "Cookies").touch()
    monkeypatch.setattr(metabase, "_CHROMIUM_PROFILE_ROOTS", {"chrome": [chrome_root]})

    targets = metabase._enumerate_cookie_files("chrome")
    cookie_files = [str(p) for _, p in targets]
    assert any("Default/Cookies" in p for p in cookie_files)
    assert any("Profile 1/Cookies" in p for p in cookie_files)


def test_load_cookies_unsupported_browser_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBC3:
        pass

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    with pytest.raises(click.ClickException, match="Unsupported browser"):
        metabase._load_cookies_from_browser("metabase.prod-us.posthog.dev", "lynx")


def test_metabase_cookie_command_errors_when_no_cache(cache_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:cookie", "--region", "us"])
    assert result.exit_code != 0
    assert "No cached cookie" in result.output


def test_metabase_cookie_command_prints_cached_value(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc; metabase.DEVICE=def")
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:cookie", "--region", "us"])
    assert result.exit_code == 0, result.output
    assert "metabase.SESSION=abc; metabase.DEVICE=def" in result.output


def test_metabase_cookie_check_validates_via_http(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc; metabase.DEVICE=d; ph_int_auth-0=a; ph_int_auth-1=b")
    runner = CliRunner()
    with patch.object(metabase, "_check_cookie", return_value=False) as check:
        result = runner.invoke(cli, ["metabase:cookie", "--region", "us", "--check"])
    assert result.exit_code != 0
    assert "no longer valid" in result.output
    check.assert_called_once()


def test_metabase_login_writes_cookie_after_validation(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {
        "metabase.SESSION": "s",
        "metabase.DEVICE": "d",
        "ph_int_auth-0": "a0",
        "ph_int_auth-1": "a1",
    }
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda domain, browser: captured)
    monkeypatch.setattr(metabase, "_check_cookie", lambda domain, header: True)
    monkeypatch.setattr(metabase.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--region", "eu", "--no-open"])
    assert result.exit_code == 0, result.output

    saved = (cache_dir / "cookie-eu").read_text()
    assert saved == "metabase.SESSION=s; metabase.DEVICE=d; ph_int_auth-0=a0; ph_int_auth-1=a1"
    mode = os.stat(cache_dir / "cookie-eu").st_mode & 0o777
    assert mode == 0o600


def test_metabase_login_requires_region_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--no-open"])
    assert result.exit_code != 0
    assert "--region" in result.output


def test_metabase_login_fast_paths_already_valid_session(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {name: f"{name}-val" for name in metabase.REQUIRED_COOKIES}
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda domain, browser: captured)
    monkeypatch.setattr(metabase, "_check_cookie", lambda domain, header: True)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)
    opens: list[str] = []
    monkeypatch.setattr(metabase.webbrowser, "open", lambda url: opens.append(url) or True)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--region", "us"])
    assert result.exit_code == 0, result.output
    assert opens == [], "browser should not open when session is already valid"
    assert "already logged in" in result.output


def test_wait_for_valid_cookie_returns_when_session_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = [
        {},
        {"metabase.SESSION": "s"},
        {name: name + "-val" for name in metabase.REQUIRED_COOKIES},
    ]
    calls = iter(sequence)
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda d, b: next(calls))
    monkeypatch.setattr(metabase, "_check_cookie", lambda d, h: True)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    header = metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)
    expected = metabase._format_cookie_header({name: name + "-val" for name in metabase.REQUIRED_COOKIES})
    assert header == expected


def test_wait_for_valid_cookie_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda d, b: {})
    monkeypatch.setattr(metabase, "_check_cookie", lambda d, h: False)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    fake_now = iter([0.0, 0.0, 100.0])  # checked twice (entry + after first sleep), then expired
    monkeypatch.setattr(metabase.time, "monotonic", lambda: next(fake_now))

    with pytest.raises(click.ClickException, match="Timed out"):
        metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)
