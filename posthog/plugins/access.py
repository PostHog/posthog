from django.conf import settings


def in_multi_tenancy():
    return getattr(settings, "MULTI_TENANCY", False)


def can_install_plugins_via_api():
    return settings.PLUGINS_INSTALL_VIA_API and not in_multi_tenancy()


def can_configure_plugins_via_api():
    return settings.PLUGINS_CONFIGURE_VIA_API and not in_multi_tenancy()
