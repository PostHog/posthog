from collections.abc import Callable
from dataclasses import field
from urllib.parse import quote

from django.contrib import admin, messages
from django.db.models import Model
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.dataclasses import frozen
from posthog.models.team.team import Team


@frozen
class MovedRecord:
    """The console record an old URL leads to, as a resolver of a moved action finds it."""

    pk: object
    # Query parameters the redirect sets on top of the old URL's own, for example the document a form preselects.
    query: dict[str, str] = field(default_factory=dict)


# Takes the keyword arguments of the old URL pattern. Returns None when nothing matches the old URL, which is a 404.
MovedRecordResolver = Callable[..., MovedRecord | None]


@frozen
class MovedAction:
    """An old Django admin URL of a record action that now lives on a console record page."""

    # A Django path pattern under admin/, for example "admin/posthog/team/<int:pk>/rebuild-cache/".
    old_path: str
    # A key of RECORD_TYPES, for example "team".
    record: str
    # Relative to the console record page: an operation form such as "api-token/set/", or an anchor such as
    # "#panel-remote-config".
    target: str
    # Without a resolver, the old path names the record's primary key `pk`.
    resolver: MovedRecordResolver | None = None


@frozen
class MovedPage:
    """An old URL of a Django admin page that now lives in the console."""

    old_path: str
    # Names the page in the notice staff see once, for example "Health checks".
    title: str
    # Where the page lives now. A path parameter of `old_path` goes in as {name}, for example "?check={kind}".
    url: str
    # Replaces the bookmark hint in the notice, when the new page alone does not show staff where to go next.
    note: str = ""


class MovedToConsole:
    """A Django admin notice that points staff to where an action lives in the console now.

    Put it where the old button was, so staff who look in the usual place find the new one.
    """

    @staticmethod
    def page_redirect(title: str, url: str, note: str = "") -> Callable[..., HttpResponse]:
        """A view for the old URL of a page that moved. It says so once, so a bookmark does not move silently."""

        def view(request: HttpRequest, **url_kwargs: object) -> HttpResponse:
            messages.info(request, f"{title} moved to PostHog Admin. {note or 'Update your bookmark to this page.'}")
            # Old URLs with a path parameter, such as a health check kind, name it in `url` as {kind}.
            target = url.format(**{name: quote(str(value), safe="") for name, value in url_kwargs.items()})
            query = request.META.get("QUERY_STRING", "")
            separator = "&" if "?" in target else "?"
            return HttpResponseRedirect(target + (f"{separator}{query}" if query else ""))

        # Like every console route, an old URL answers only to signed-in staff.
        return admin.site.admin_view(view)

    @staticmethod
    def record_redirect(
        plural: str, target: str, resolver: MovedRecordResolver | None = None
    ) -> Callable[..., HttpResponse]:
        """A view for the old URL of a record action that moved. `target` is relative to the console record page."""

        def view(request: HttpRequest, **url_kwargs: object) -> HttpResponse:
            moved = resolver(**url_kwargs) if resolver is not None else MovedRecord(pk=url_kwargs["pk"])
            if moved is None:
                raise Http404("Nothing matches this old link")
            messages.info(request, "This action moved to PostHog Admin. Update your bookmark to this page.")
            if moved.query:
                params = request.GET.copy()
                for name, value in moved.query.items():
                    params[name] = value
                query = params.urlencode()
            else:
                query = request.META.get("QUERY_STRING", "")
            page, _, anchor = target.partition("#")
            return HttpResponseRedirect(
                f"/admin/console/{plural}/{moved.pk}/{page}"
                + (f"?{query}" if query else "")
                + (f"#{anchor}" if anchor else "")
            )

        # Like every console route, an old URL answers only to signed-in staff.
        return admin.site.admin_view(view)

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
