from django.contrib import admin
from django.urls import NoReverseMatch, reverse

from posthog.admin import register_all_admin


def test_admin_app_list_url_covers_every_registered_admin_app():
    # The URL conf has to load first, because `AdminSite.get_urls()` freezes the
    # `admin:app_list` pattern over the registry it finds and never rebuilds it.
    # The second line then registers anything the URL conf left out.
    reverse("admin:index")
    register_all_admin()

    unreachable = []
    for app_label in sorted({model._meta.app_label for model in admin.site._registry}):
        try:
            reverse("admin:app_list", kwargs={"app_label": app_label})
        except NoReverseMatch:
            unreachable.append(app_label)

    assert not unreachable, (
        f"These admin apps registered after the admin URL conf was built: {unreachable}. "
        "The admin URL conf must call register_all_admin() before it reads admin.site.urls."
    )
