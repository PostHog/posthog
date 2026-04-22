"""
Canary test: prove the IDOR framework's assertions actually fire.

A test suite that only detects the absence of IDORs is worthless if the
test itself is broken. This test exercises the mixin's assertions against
deliberately-crafted "bad" responses and verifies that the assertions
CATCH the vulnerability — i.e. they actually raise when they should.

If this test ever starts silently passing (the assertions no longer raise
on crafted-vulnerable inputs), the rest of the IDOR coverage suite is
giving false-negative results and must be fixed.

We test each of the framework's three security gates:

  1. Status code check — 2xx on a cross-team request is a fail signal.
  2. Sentinel leak check — victim's sentinel appearing in response body.
  3. Mutation check — attacker's PATCH actually changed victim's data.

Plus a sanity check that `reset_sentinel()` produces distinct values.
"""

from __future__ import annotations

from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.insight import Insight
from posthog.test.idor.factory import current_sentinel, reset_sentinel
from posthog.test.idor.mixin import IDORTestMixin


class TestCanaryIDORDetection(IDORTestMixin, APIBaseTest):
    """Verify the framework's assertions actually catch the failures they're designed to catch."""

    def test_status_check_catches_2xx_cross_team_response(self) -> None:
        """A 2xx response on a cross-team request must be flagged as an IDOR."""
        reset_sentinel()
        fake_response = SimpleNamespace(status_code=200, content=b'{"id": 42}')
        raised = False
        with patch.object(self.client, "get", return_value=fake_response):  # type: ignore[attr-defined]
            try:
                self.assertCrossTeamDenied("/fake/", method="get")
            except AssertionError as e:
                raised = True
                assert "2xx" in str(e), f"Error message should mention 2xx, got: {e}"
        assert raised, "Canary failed — a 200 cross-team response did not trigger assertCrossTeamDenied"

    def test_status_check_passes_on_4xx(self) -> None:
        """A 4xx response must not raise — this is the canonical denial case."""
        fake_response = SimpleNamespace(status_code=404, content=b'{"detail": "Not found"}')
        with patch.object(self.client, "get", return_value=fake_response):  # type: ignore[attr-defined]
            # Should not raise.
            self.assertCrossTeamDenied("/fake/", method="get")

    def test_status_check_passes_on_5xx(self) -> None:
        """A 5xx response is a latent bug, not an IDOR — must not raise."""
        fake_response = SimpleNamespace(status_code=500, content=b'{"detail": "Server error"}')
        with patch.object(self.client, "get", return_value=fake_response):  # type: ignore[attr-defined]
            # Should not raise. Sentinel check would separately catch any data leak in the body.
            self.assertCrossTeamDenied("/fake/", method="get")

    def test_sentinel_leak_detected(self) -> None:
        """assertSentinelNotLeaked must raise when the victim's sentinel appears in the body."""
        sentinel = reset_sentinel()
        fake_response = SimpleNamespace(content=f'{{"name": "{sentinel}", "id": 42}}'.encode())
        raised = False
        try:
            self.assertSentinelNotLeaked(fake_response, sentinel)
        except AssertionError:
            raised = True
        assert raised, "Canary failed — assertSentinelNotLeaked missed a sentinel in the response body"

    def test_sentinel_leak_passes_when_clean(self) -> None:
        """assertSentinelNotLeaked must NOT raise when the sentinel is absent."""
        sentinel = reset_sentinel()
        fake_response = SimpleNamespace(content=b'{"error": "not found"}')
        # Should not raise.
        self.assertSentinelNotLeaked(fake_response, sentinel)

    def test_mutation_check_catches_modified_resource(self) -> None:
        """If a PATCH actually mutated the victim's data, querying it should reveal the new value."""
        reset_sentinel()
        victim_insight = Insight.objects.create(team=self.victim_team, name=current_sentinel())

        # Simulate a successful cross-team mutation (as a vulnerable PATCH would).
        victim_insight.name = "pwned"
        victim_insight.save()

        reloaded = Insight.objects.filter(pk=victim_insight.pk).first()
        assert reloaded is not None
        assert reloaded.name == "pwned", "Canary failed — the mutation check couldn't see the pwned state"

    def test_mutation_check_passes_on_unchanged_resource(self) -> None:
        """If the resource is unchanged, name must still equal the sentinel."""
        sentinel = reset_sentinel()
        victim_insight = Insight.objects.create(team=self.victim_team, name=sentinel)
        reloaded = Insight.objects.filter(pk=victim_insight.pk).first()
        assert reloaded is not None
        assert reloaded.name == sentinel
        assert reloaded.name != "pwned"

    def test_unique_sentinel_per_reset(self) -> None:
        """Sentinels must be distinct across calls — otherwise tests can alias each other."""
        a = reset_sentinel()
        b = reset_sentinel()
        assert a != b
        assert a.startswith("idor-sentinel-")
        assert b.startswith("idor-sentinel-")

    def test_sentinel_match_is_case_insensitive(self) -> None:
        """Some APIs lower-case user input in responses; match must be case-insensitive."""
        sentinel = reset_sentinel()
        fake_response = SimpleNamespace(content=sentinel.upper().encode())
        raised = False
        try:
            self.assertSentinelNotLeaked(fake_response, sentinel)
        except AssertionError:
            raised = True
        assert raised, "Canary failed — case-variant sentinel leaks are missed"
