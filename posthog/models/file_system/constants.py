from django.db.models import Q

# The product surface a FileSystem row belongs to. Legacy rows predate this column and are
# stored as NULL; they are read as the default ("web"). New rows always store an explicit value.
DEFAULT_SURFACE = "web"

# Surface for the desktop product tree, fully isolated from the default "web" tree.
DESKTOP_SURFACE = "desktop"


def surface_q(surface: str) -> Q:
    """Build the read filter for a surface. The default surface also matches legacy NULL rows."""
    if surface == DEFAULT_SURFACE:
        return Q(surface__isnull=True) | Q(surface=DEFAULT_SURFACE)
    return Q(surface=surface)
