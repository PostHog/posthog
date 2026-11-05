from collections.abc import Callable

from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.models.team.team import Team


class MovedToConsole:
    """A Django admin notice that points staff to where an action lives in the console now.

    Put it where the old button was, so staff who look in the usual place find the new one.
    """

    @staticmethod
    def page_redirect(title: str, url: str) -> Callable[[HttpRequest], HttpResponse]:
        """A view for the old URL of a page that moved. It says so once, so a bookmark does not move silently."""

        def view(request: HttpRequest) -> HttpResponse:
            messages.info(request, f"{title} moved to PostHog Admin. Update your bookmark to this page.")
            query = request.META.get("QUERY_STRING", "")
            return HttpResponseRedirect(url + (f"?{query}" if query else ""))

        return view

    @staticmethod
    def record_redirect(plural: str, target: str) -> Callable[..., HttpResponse]:
        """A view for the old URL of a record action that moved. `target` is relative to the console record page.

        The old URL pattern names its primary key `pk`, for example `admin/posthog/team/<int:pk>/rebuild-cache/`.
        """

        def view(request: HttpRequest, pk: object) -> HttpResponse:
            messages.info(request, "This action moved to PostHog Admin. Update your bookmark to this page.")
            page, _, anchor = target.partition("#")
            query = request.META.get("QUERY_STRING", "")
            return HttpResponseRedirect(
                f"/admin/console/{plural}/{pk}/{page}"
                + (f"?{query}" if query else "")
                + (f"#{anchor}" if anchor else "")
            )

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
