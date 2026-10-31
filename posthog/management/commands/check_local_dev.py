import json
import base64
import hashlib
import secrets
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import requests

from posthog.management.commands.setup_local_dev import LocalDevSetup
from posthog.models import User
from posthog.models.oauth import OAuthGrant
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.facade.local_demo import local_demo_task_ids

if TYPE_CHECKING:
    from argparse import ArgumentParser


class LocalDevCheck:
    def __init__(self, callback: str) -> None:
        self.host = settings.SITE_URL.rstrip("/")
        self.callback = callback
        self.session = requests.Session()
        self.session.trust_env = False
        self.access_token = ""
        self.refresh_token = ""

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        data: dict[str, str] | None = None,
    ) -> requests.Response:
        headers = {
            "Accept": "application/json",
            "Origin": self.host,
            "Referer": self.host + "/",
            "X-CSRFToken": self.session.cookies.get(settings.CSRF_COOKIE_NAME, ""),
        }
        if self.access_token and path.startswith("/api/"):
            headers["Authorization"] = f"Bearer {self.access_token}"
        response = self.session.request(
            method,
            self.host + path,
            headers=headers,
            timeout=30,
            allow_redirects=False,
            params=params,
            json=json,
            data=data,
        )
        if response.status_code != 200:
            raise CommandError(f"{method} {path} returned HTTP {response.status_code}. Check the local server logs.")
        return response

    def logout(self) -> None:
        if self.session.cookies.get(settings.SESSION_COOKIE_NAME):
            response = self.session.post(
                self.host + "/logout/",
                headers={
                    "X-CSRFToken": self.session.cookies.get(settings.CSRF_COOKIE_NAME, ""),
                    "Origin": self.host,
                    "Referer": self.host + "/",
                },
                timeout=30,
                allow_redirects=False,
            )
            if response.status_code not in {200, 302}:
                raise CommandError(f"Local logout returned HTTP {response.status_code}. Check the server logs.")

    @staticmethod
    def check_conversation_messages(logs: str) -> None:
        roles: set[str] = set()
        try:
            for line in logs.splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                update = entry.get("notification", {}).get("params", {}).get("update", {})
                if update.get("sessionUpdate") in {"user_message", "agent_message"}:
                    content = update.get("content", {})
                    text = content.get("text")
                    if content.get("type") == "text" and isinstance(text, str) and text.strip():
                        roles.add(update["sessionUpdate"])
        except (ValueError, AttributeError, TypeError) as error:
            raise CommandError("The saved demo conversation has invalid logs. Check local object storage.") from error
        if roles != {"user_message", "agent_message"}:
            raise CommandError(
                "The saved demo conversation is missing its user or assistant message. "
                "Check local object storage, then run `python manage.py setup_local_dev` to repair a missing log."
            )

    def check_demo_chat(self, team_id: int, user_id: int) -> None:
        demo = local_demo_task_ids(team_id=team_id, user_id=user_id)
        task_path = f"/api/projects/{team_id}/tasks/{demo.task_id}/"
        self.request("GET", task_path)
        run_path = f"{task_path}runs/{demo.run_id}/"
        run = self.request("GET", run_path).json()
        if run.get("status") != "completed":
            raise CommandError("The seeded demo conversation is not completed. Check the local task's run state.")
        self.check_conversation_messages(self.request("GET", run_path + "logs/").text)

    def run(self) -> dict[str, object]:
        LocalDevSetup.check_environment()
        user = User.objects.filter(email__iexact="test@posthog.com").first()
        if user is None or user.current_team_id is None:
            raise CommandError("Run `python manage.py setup_local_dev` first.")
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(24)
        params = {
            "client_id": ARRAY_APP_CLIENT_ID_DEV,
            "redirect_uri": self.callback,
            "response_type": "code",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="),
            "code_challenge_method": "S256",
            "state": state,
            "scope": "openid profile email user:read organization:read project:read task:read today:read dashboard:read insight:read file_system_shortcut:read",
        }
        code = ""
        try:
            self.request("GET", "/login/")
            self.request("POST", "/api/login/", json={"email": user.email, "password": "12345678"})
            self.request("GET", "/oauth/authorize/", params=params)
            consent = self.request(
                "POST",
                "/oauth/authorize/",
                json={**params, "allow": True, "access_level": "all", "scoped_teams": [], "scoped_organizations": []},
            ).json()
            callback = urlsplit(consent.get("redirect_to", ""))
            if callback._replace(query="", fragment="").geturl() != self.callback:
                raise CommandError("OAuth returned an unexpected callback. Check setup_tasks_oauth.")
            query = parse_qs(callback.query)
            if query.get("state") != [state] or not query.get("code"):
                raise CommandError("OAuth callback did not contain the expected state and authorization code.")
            code = query["code"][0]
            tokens = self.request(
                "POST",
                "/oauth/token/",
                json={
                    "grant_type": "authorization_code",
                    "client_id": ARRAY_APP_CLIENT_ID_DEV,
                    "redirect_uri": self.callback,
                    "code_verifier": verifier,
                    "code": code,
                },
            ).json()
            self.access_token = tokens["access_token"]
            self.refresh_token = tokens["refresh_token"]
            self.logout()
            self.session.cookies.clear()
            me = self.request("GET", "/api/users/@me/").json()
            if me["id"] != user.pk:
                raise CommandError("OAuth authenticated a different account.")
            team_id = user.current_team_id
            self.request("GET", f"/api/organizations/{user.current_team.organization_id}/")
            self.request("GET", f"/api/projects/{team_id}/")
            reports = self.request(
                "GET", f"/api/projects/{team_id}/signals/reports/?view=for_you&sort=priority&limit=20&offset=0"
            ).json()["results"]
            tasks = self.request(
                "GET",
                f"/api/projects/{team_id}/tasks/?basic=true&created_by={user.pk}&exclude_origin_product=signals_scout",
            ).json()["results"]
            self.request("GET", f"/api/projects/{team_id}/dashboards/?basic=true")
            self.request("GET", f"/api/projects/{team_id}/insights/?basic=true&refresh=force_cache")
            self.request("GET", f"/api/projects/{team_id}/file_system_shortcut/?limit=100")
            if not reports or not tasks:
                raise CommandError("The local inbox or task list is empty. Run `python manage.py setup_local_dev`.")
            self.request("GET", f"/api/projects/{team_id}/signals/reports/{reports[0]['id']}/")
            self.check_demo_chat(team_id, user.pk)
            refreshed = self.request(
                "POST",
                "/oauth/token/",
                json={
                    "grant_type": "refresh_token",
                    "client_id": ARRAY_APP_CLIENT_ID_DEV,
                    "refresh_token": self.refresh_token,
                },
            ).json()
            self.access_token = refreshed["access_token"]
            self.refresh_token = refreshed.get("refresh_token", self.refresh_token)
            self.request("GET", "/api/users/@me/")
            self.revoke()
            denied = self.session.get(
                self.host + "/api/users/@me/",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=30,
                allow_redirects=False,
            )
            if denied.status_code not in {401, 403}:
                raise CommandError("The revoked OAuth session still has API access.")
            return {
                "user_id": user.pk,
                "team_id": team_id,
                "report_count": len(reports),
                "task_count": len(tasks),
                "conversation": "passed",
                "oauth": "passed",
            }
        finally:
            try:
                self.revoke()
            finally:
                if code:
                    OAuthGrant.objects.filter(
                        code=code, user=user, application__client_id=ARRAY_APP_CLIENT_ID_DEV
                    ).delete()
                try:
                    self.logout()
                finally:
                    self.session.close()

    def revoke(self) -> None:
        if self.refresh_token:
            self.request(
                "POST",
                "/oauth/revoke/",
                data={
                    "client_id": ARRAY_APP_CLIENT_ID_DEV,
                    "token": self.refresh_token,
                    "token_type_hint": "refresh_token",
                },
            )
            self.refresh_token = ""


class Command(BaseCommand):
    help = "Check local password login, OAuth PKCE, authenticated reads, refresh, and revocation over HTTP"

    def add_arguments(self, parser: "ArgumentParser") -> None:
        parser.add_argument("--json", action="store_true", help="Print only a safe summary of the authenticated check")
        parser.add_argument(
            "--callback",
            choices=["posthog://callback", "posthog-dev://callback", "posthog-preview://callback"],
            default="posthog-dev://callback",
        )

    def handle(self, *args: object, **options: object) -> None:
        try:
            result = LocalDevCheck(str(options["callback"])).run()
        except (requests.RequestException, ValueError, KeyError) as error:
            raise CommandError(
                "The authenticated local check failed. Check local server logs and run setup_local_dev."
            ) from error
        self.stdout.write(
            json.dumps(result)
            if options["json"]
            else "Local OAuth PKCE, account, project, inbox, tasks, refresh, and revocation checks passed."
        )
