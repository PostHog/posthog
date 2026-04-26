"""
IDORTestMixin — fixtures and assertion helpers for cross-tenant IDOR tests.

Inherit alongside APIBaseTest:

    class TestSomething(IDORTestMixin, APIBaseTest):
        def test_foo(self):
            self.assertCrossTeamDenied(url)

At class setup the mixin creates a second org/team/user (the `victim`)
so tests can create resources there and then use the APIBaseTest-provided
attacker (`self.user` in `self.team`) to verify cross-tenant access is
blocked.

Organization-scoped viewsets can use `self.victim_org` / `self.organization`
for cross-org testing.
"""

from __future__ import annotations

from typing import Any, ClassVar, Optional

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.models.user import User

# Status codes that indicate the attacker's request succeeded with the victim's resource.
# Any 2xx is treated as "success" from the attacker's perspective — potentially an IDOR
# (though the sentinel and mutation checks are the real security gates). Anything outside
# 2xx is treated as "denied" regardless of whether it's the cleanest possible response:
#   - 400 (validation), 403 (perm), 404 (not in queryset) — canonical denials
#   - 405 (method not supported) — not an IDOR either way
#   - 5xx — latent viewset bug but no data leak (sentinel check would catch if body leaks)
SUCCESS_2XX = frozenset(range(200, 300))


class IDORTestMixin:
    """Adds `victim_*` fixtures and cross-team assertion helpers."""

    # Declared as ClassVar so subclasses don't trip type checkers when
    # accessing them on instances.
    victim_org: ClassVar[Organization]
    victim_project: ClassVar[Project]
    victim_team: ClassVar[Team]
    victim_user: ClassVar[User]

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()  # type: ignore[misc]
        cls.victim_org = Organization.objects.create(name="Victim Org (IDOR test)")
        cls.victim_project = Project.objects.create(
            id=Team.objects.increment_id_sequence(),
            organization=cls.victim_org,
            name="Victim Project",
        )
        cls.victim_team = Team.objects.create(
            id=cls.victim_project.id,
            project=cls.victim_project,
            organization=cls.victim_org,
            name="Victim Team",
        )
        cls.victim_user = User.objects.create_and_join(
            cls.victim_org, "victim+idor@posthog.com", password="victimpassword12345"
        )

    # ---- Assertions --------------------------------------------------------

    def assertCrossTeamDenied(
        self,
        url: str,
        method: str = "get",
        data: Optional[dict] = None,
        message: str = "",
    ) -> Any:
        """Attacker (self.user) hits `url`; expect a non-2xx response.

        2xx status codes are treated as IDOR hits (the attacker received a
        success response for a cross-team resource). Any other status code
        (4xx, 5xx) is treated as denied. The caller should additionally run
        `assertSentinelNotLeaked` on the response to catch info-leaks that
        happen inside an error body, and (for PATCH/DELETE) verify the
        victim's resource wasn't actually mutated.
        """
        http_method = getattr(self.client, method.lower())  # type: ignore[attr-defined]
        response = http_method(url, data=data) if data is not None else http_method(url)
        status_code = response.status_code
        if status_code in SUCCESS_2XX:
            raise AssertionError(
                f"IDOR: {method.upper()} {url} returned {status_code} (2xx); "
                f"attacker should not get a success response for a cross-team resource. "
                f"{message}"
                f"\nResponse: {response.content[:400]!r}"
            )
        return response

    def assertSentinelNotLeaked(self, response: Any, sentinel: str) -> None:
        """Assert a unique sentinel string (e.g. from the victim's resource) isn't in the response body."""
        body = response.content.decode("utf-8", errors="replace")
        if sentinel.lower() in body.lower():
            raise AssertionError(f"IDOR info leak: sentinel {sentinel!r} appeared in response body: {body[:400]!r}")

    def assertCrossOrgDenied(
        self,
        url: str,
        method: str = "get",
        data: Optional[dict] = None,
        message: str = "",
    ) -> Any:
        """Attacker (self.user) hits a URL that targets the victim's tenant root.

        Same shape as `assertCrossTeamDenied`: any 2xx is treated as a hit,
        anything else is denied. Used by the cross-org root parametric to
        confirm Organization / Project / Team viewsets reject requests that
        target a tenant the attacker isn't a member of.
        """
        return self.assertCrossTeamDenied(url, method=method, data=data, message=message)
