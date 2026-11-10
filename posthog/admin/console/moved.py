from collections.abc import Callable
from urllib.parse import quote

from django.contrib import admin, messages
from django.db.models import Model
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team


class MovedToConsole:
    """A Django admin notice that points staff to where an action lives in the console now.

    Put it where the old button was, so staff who look in the usual place find the new one.
    """

    @staticmethod
    def page_redirect(title: str, url: str) -> Callable[..., HttpResponse]:
        """A view for the old URL of a page that moved. It says so once, so a bookmark does not move silently."""

        def view(request: HttpRequest, **url_kwargs: object) -> HttpResponse:
            messages.info(request, f"{title} moved to PostHog Admin. Update your bookmark to this page.")
            # Old URLs with a path parameter, such as a health check kind, name it in `url` as {kind}.
            target = url.format(**{name: quote(str(value), safe="") for name, value in url_kwargs.items()})
            query = request.META.get("QUERY_STRING", "")
            separator = "&" if "?" in target else "?"
            return HttpResponseRedirect(target + (f"{separator}{query}" if query else ""))

        # Like every console route, an old URL answers only to signed-in staff.
        return admin.site.admin_view(view)

    @staticmethod
    def record_redirect(plural: str, target: str) -> Callable[..., HttpResponse]:
        """A view for the old URL of a record action that moved. `target` is relative to the console record page.

        The old URL pattern names its primary key `pk`, for example `admin/posthog/team/<int:pk>/rebuild-cache/`.
        """

        def view(request: HttpRequest, pk: object, query: str | None = None) -> HttpResponse:
            messages.info(request, "This action moved to PostHog Admin. Update your bookmark to this page.")
            page, _, anchor = target.partition("#")
            if query is None:
                query = request.META.get("QUERY_STRING", "")
            return HttpResponseRedirect(
                f"/admin/console/{plural}/{pk}/{page}"
                + (f"?{query}" if query else "")
                + (f"#{anchor}" if anchor else "")
            )

        return view

    @staticmethod
    def owner_redirect(locate: Callable[[str], str | None]) -> Callable[..., HttpResponse]:
        """A view for the old URL of an action on a row that has no console page, such as an API key.

        `locate` returns where the action lives now, on the page of the record that owns the row, or None when no
        row has the old primary key.
        """

        def view(request: HttpRequest, pk: str) -> HttpResponse:
            target = locate(pk)
            if target is None:
                raise Http404("Nothing matches this old link")
            messages.info(request, "This action moved to PostHog Admin. Update your bookmark to this page.")
            page, _, anchor = target.partition("#")
            query = request.META.get("QUERY_STRING", "")
            return HttpResponseRedirect(page + (f"?{query}" if query else "") + (f"#{anchor}" if anchor else ""))

        return view

    @staticmethod
    def action(record: str, obj: Model, panel_key: str, action: str) -> SafeString:
        url = reverse(f"admin_console_{record}", kwargs={"pk": obj.pk})
        return format_html(
            '<a href="{}#panel-{}">{}: now in PostHog Admin &#8599;</a>',
            url,
            panel_key,
            action,
        )

    @classmethod
    def team_action(cls, team: Team, panel_key: str, action: str) -> SafeString:
        return cls.action("team", team, panel_key, action)


class MovedKeyActions:
    """Where the roll action of an API key lives now: in a panel on the page of the user or team that owns it."""

    @staticmethod
    def personal_api_key(pk: str) -> str | None:
        # nosemgrep: idor-lookup-without-user -- staff-only redirect behind admin_view; it finds the key's owner to link there
        user_id = PersonalAPIKey.objects.filter(pk=pk).values_list("user_id", flat=True).first()
        if user_id is None:
            return None
        return reverse("admin_console_user", kwargs={"pk": user_id}) + "#panel-personal-api-keys"

    @staticmethod
    def project_secret_api_key(pk: str) -> str | None:
        # nosemgrep: idor-lookup-without-team -- staff-only redirect behind admin_view; it finds the key's team to link there
        team_id = ProjectSecretAPIKey.objects.filter(pk=pk).values_list("team_id", flat=True).first()
        if team_id is None:
            return None
        return reverse("admin_console_team", kwargs={"pk": team_id}) + "#panel-secret-api-keys"
