from django.conf import settings


def can_install_plugins_via_api():
    return settings.PLUGINS_INSTALL_VIA_API and not getattr(settings, "MULTI_TENANCY", False)


def can_configure_plugins_via_api():
    return settings.PLUGINS_CONFIGURE_VIA_API and not getattr(settings, "MULTI_TENANCY", False)
