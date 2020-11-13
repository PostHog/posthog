from django.conf import settings


# We disable all plugins under multi-tenancy. For safety. Eventually we will remove this block.
# For now, removing this in TEST mode, so that we can be sure plugins actually work in EE if/when needed.
def not_in_multi_tenancy():
    return settings.TEST or not getattr(settings, "MULTI_TENANCY", False)


def can_install_plugins_via_api():
    return settings.PLUGINS_INSTALL_VIA_API and not_in_multi_tenancy()


def can_configure_plugins_via_api():
    return settings.PLUGINS_CONFIGURE_VIA_API and not_in_multi_tenancy()
