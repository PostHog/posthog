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

# Status codes that indicate the attacker was blocked:
#   403 — permission check fired (e.g. TeamMemberAccessPermission)
#   404 — queryset filter returned empty (canonical IDOR defense)
#   405 — method not supported on this viewset for anyone (not an IDOR either way)
DENIED_STATUS_CODES = frozenset({403, 404, 405})


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
        """Attacker (self.user) hits `url`; expect one of DENIED_STATUS_CODES.

        Returns the response so callers can do extra assertions (e.g. info-leak
        sentinel checks).
        """
        http_method = getattr(self.client, method.lower())  # type: ignore[attr-defined]
        response = http_method(url, data=data) if data is not None else http_method(url)
        status_code = response.status_code
        if status_code not in DENIED_STATUS_CODES:
            raise AssertionError(
                f"IDOR: {method.upper()} {url} returned {status_code}; "
                f"expected one of {sorted(DENIED_STATUS_CODES)}. "
                f"{message}"
                f"\nResponse: {response.content[:400]!r}"
            )
        return response

    def assertSentinelNotLeaked(self, response: Any, sentinel: str) -> None:
        """Assert a unique sentinel string (e.g. from the victim's resource) isn't in the response body."""
        body = response.content.decode("utf-8", errors="replace")
        if sentinel.lower() in body.lower():
            raise AssertionError(f"IDOR info leak: sentinel {sentinel!r} appeared in response body: {body[:400]!r}")
