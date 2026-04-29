"""Meta-test: walk every URL pattern and verify the guest deflection middleware would
either deflect a no-grant guest or match an `AlwaysAllowed` rule.

This is the fail-safe-defaults invariant: a developer adding a new endpoint cannot
accidentally leak it to a guest who has no grants. Without this test, the surface only
stays correct via vigilance.

The test iterates over the URL patterns Django has loaded, samples a concrete URL for
each (substituting `<int:team_id>` etc. with sentinel values), and for each (URL, method)
combination, asks the middleware which rule (if any) would match.

- No rule matches → middleware would deflect → ✅
- Matches `AlwaysAllowed` → reviewed allow → ✅
- Matches a Grant*/SceneBound* rule whose `allows()` returns False for the no-grant guest
  → middleware would deflect → ✅
- Matches a Grant*/SceneBound* rule whose `allows()` returns True for the no-grant guest
  → ❌ leak

The test runs the middleware purely in-process via `RequestFactory`; no real HTTP calls.
"""

import re
from collections.abc import Iterator

import pytest
from posthog.test.base import APIBaseTest

from django.test import RequestFactory
from django.urls import URLPattern, URLResolver, get_resolver

from posthog.middleware_guest import GUEST_RULES, AlwaysAllowed
from posthog.models import OrganizationMembership
from posthog.models.user import User

_SAMPLE_VALUES: dict[str, str] = {
    # Numeric ids — the team scope is the most common, plus generic pk/id/parent_lookup_*
    "team_id": "1",
    "parent_lookup_team_id": "1",
    "project_id": "1",
    "parent_lookup_project_id": "1",
    "id": "1",
    "pk": "1",
    "tile_id": "1",
    "subscription_id": "1",
    "annotation_id": "1",
    "cohort_id": "1",
    "feature_flag_id": "1",
    "session_recording_id": "1",
    "experiment_id": "1",
    "dashboard_id": "1",
    "insight_id": "1",
    "person_id": "1",
    # short_id-style identifiers (insights, notebooks, sessions)
    "short_id": "ABC12345",
    # UUIDs — invites, organizations, members, OAuth apps
    "uuid": "00000000-0000-0000-0000-000000000001",
    "organization_id": "00000000-0000-0000-0000-000000000001",
    "parent_lookup_organization_id": "00000000-0000-0000-0000-000000000001",
    "membership_id": "00000000-0000-0000-0000-000000000001",
    "invite_id": "00000000-0000-0000-0000-000000000001",
    "client_id": "00000000-0000-0000-0000-000000000001",
    "key_id": "00000000-0000-0000-0000-000000000001",
}


def _sample_for(name: str) -> str:
    return _SAMPLE_VALUES.get(name, "1")


_PATH_CONVERTER_RE = re.compile(r"<(?:int|str|uuid|slug|path|drf_format_suffix(?::\w+)?):(\w+)>")
_BARE_CONVERTER_RE = re.compile(r"<(\w+)>")
_NAMED_GROUP_RE = re.compile(r"\(\?P<(\w+)>[^)]*\)")
_NON_CAPTURING_RE = re.compile(r"\(\?:[^)]*\)\??")
_BARE_GROUP_RE = re.compile(r"\((?!\?)[^)]*\)\??")
_REGEX_META = "[]{}|+*\\"


_CHAR_CLASS_RE = re.compile(r"\[[^\]]+\]\+|\\d\+|\\w\+")


def _pattern_to_url(pattern_str: str) -> str | None:
    """Best-effort: turn a Django URL pattern string into a concrete sample URL."""
    s = pattern_str
    s = _PATH_CONVERTER_RE.sub(lambda m: _sample_for(m.group(1)), s)
    s = _BARE_CONVERTER_RE.sub(lambda m: _sample_for(m.group(1)), s)
    s = _NAMED_GROUP_RE.sub(lambda m: _sample_for(m.group(1)), s)
    # strip anchors
    s = s.lstrip("^").rstrip("$")
    # DRF format suffix: drop entirely so the test doesn't generate `.json` noise
    s = re.sub(r"\(\?P<format>[^)]+\)\??", "", s)
    # remaining capturing/non-capturing groups → drop the group, keep nothing inside
    s = _NON_CAPTURING_RE.sub("", s)
    s = _BARE_GROUP_RE.sub("", s)
    # bare character classes (regex routes), e.g. `[A-Za-z0-9]+`
    s = _CHAR_CLASS_RE.sub("x", s)
    # backslash escapes
    s = s.replace(r"\.", ".").replace(r"\/", "/").replace(r"\Z", "").replace(r"\$", "")
    # optional group markers and trailing slash flexibility
    s = s.replace("/?", "/").replace(".?", "")
    # collapse double slashes
    while "//" in s:
        s = s.replace("//", "/")
    # leftover regex metachars mean it's not a static path — skip safely
    if any(c in s for c in _REGEX_META):
        return None
    if not s.startswith("/"):
        s = "/" + s
    return s


def _segment(pattern) -> str:
    """Stringify a URLPattern/URLResolver pattern with internal anchors stripped so the
    parent prefix concatenates cleanly. `str(RegexPattern)` returns the raw regex with
    `^...$` anchors; concatenating two such strings produces invalid intermediates like
    `api/^foo/bar/?$` that our sampler can't handle.
    """
    s = str(pattern.pattern)
    if s.startswith("^"):
        s = s[1:]
    if s.endswith("$"):
        s = s[:-1]
    return s


def _walk_url_patterns(resolver: URLResolver, prefix: str = "") -> Iterator[tuple[str, URLPattern]]:
    for pattern in resolver.url_patterns:
        full = prefix + _segment(pattern)
        if isinstance(pattern, URLResolver):
            yield from _walk_url_patterns(pattern, full)
        elif isinstance(pattern, URLPattern):
            yield full, pattern


@pytest.mark.usefixtures("unittest_snapshot")
class TestGuestEndpointCoverage(APIBaseTest):
    """Fail-safe-defaults invariant: every endpoint either deflects a no-grant guest or
    is explicitly in the `AlwaysAllowed` allowlist. Any other rule that says yes to a
    no-grant guest is a leak.

    Includes two regression guards via syrupy snapshots:
    - The set of (method, url) pairs that match an `AlwaysAllowed` rule. Adding a new
      `AlwaysAllowed` regex (or widening an existing one) shifts this set; the snapshot
      forces human review on the diff. Update with `pytest --snapshot-update`.
    - The set of URL patterns the sampler couldn't generate a concrete URL for. A sudden
      growth indicates either a new Django syntax the sampler doesn't handle or a
      genuinely-unsampleable new route.
    """

    def test_no_endpoint_leaks_to_no_grant_guest(self) -> None:
        guest = User.objects.create_user(email="endpoint-coverage-guest@example.com", first_name="L", password="pw")
        OrganizationMembership.objects.create(organization=self.organization, user=guest, is_guest=True)

        factory = RequestFactory()
        leaks: list[dict] = []
        skipped: list[str] = []
        always_allowed_hits: list[tuple[str, str]] = []
        coverage: dict[str, int] = {
            "total_urls": 0,
            "always_allowed_hits": 0,
            "deflected_no_match": 0,
            "deflected_by_rule": 0,
        }

        for pattern_str, _pattern in _walk_url_patterns(get_resolver()):
            url = _pattern_to_url(pattern_str)
            if url is None:
                skipped.append(pattern_str)
                continue
            coverage["total_urls"] += 1
            for method in ("GET", "POST", "PATCH", "DELETE"):
                request = getattr(factory, method.lower())(url)
                request.user = guest
                matched_rule = None
                match_obj = None
                for rule in GUEST_RULES:
                    m = rule.matches(request)
                    if m:
                        matched_rule = rule
                        match_obj = m
                        break
                if matched_rule is None:
                    coverage["deflected_no_match"] += 1
                    continue
                if isinstance(matched_rule, AlwaysAllowed):
                    coverage["always_allowed_hits"] += 1
                    always_allowed_hits.append((method, url))
                    continue
                # Resource/grant-bound rule — must deny for a no-grant guest.
                try:
                    allowed = matched_rule.allows(request, guest, match_obj)
                except Exception as exc:  # pragma: no cover — safety: shouldn't crash
                    leaks.append(
                        {
                            "url": url,
                            "method": method,
                            "rule": type(matched_rule).__name__,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                if allowed:
                    leaks.append(
                        {
                            "url": url,
                            "method": method,
                            "rule": type(matched_rule).__name__,
                        }
                    )
                else:
                    coverage["deflected_by_rule"] += 1

        # Always-emit summary so a human reviewing CI logs sees the coverage stats.
        print("\nGuest endpoint coverage:")  # noqa: T201
        for k, v in coverage.items():
            print(f"  {k}: {v}")  # noqa: T201
        print(f"  url-patterns skipped (couldn't sample): {len(skipped)}")  # noqa: T201
        if leaks:
            print(f"\nLeaks ({len(leaks)}):")  # noqa: T201
            for leak in leaks:
                print(f"  {leak['method']:6}  {leak['url']:80}  rule={leak['rule']}")  # noqa: T201

        self.assertEqual(leaks, [], f"Guest mode leaks: {len(leaks)} (see stdout for details)")

        # Snapshot guards — see class docstring. Sort for determinism.
        always_allowed_snapshot = "\n".join(f"{m} {u}" for m, u in sorted(set(always_allowed_hits)))
        skipped_snapshot = "\n".join(sorted(set(skipped)))
        assert always_allowed_snapshot == self.snapshot(name="always_allowed")
        assert skipped_snapshot == self.snapshot(name="skipped_patterns")
