# Test cases for no-environments-url-path.
# ruff: noqa

from django.urls import include, path, re_path


def view(*args, **kwargs):
    pass


urlpatterns = [
    # ruleid: no-environments-url-path
    path("api/environments/<int:team_id>/thing/", view),
    # ruleid: no-environments-url-path
    path("api/environments/<int:team_id>/thing", view),
    # ruleid: no-environments-url-path
    re_path(r"^api/environments/(?P<team_id>[0-9]+)/thing/$", view),
    # ruleid: no-environments-url-path
    path(
        "api/environments/<int:parent_lookup_team_id>/thing/",
        include("products.thing.urls"),
    ),
    # ok: no-environments-url-path
    path("api/projects/<int:team_id>/thing/", view),
    # ok: no-environments-url-path
    path("api/environments_lookalike/<int:team_id>/thing/", view),
    # ok: no-environments-url-path
    path("api/unsubscribe", view),
]
