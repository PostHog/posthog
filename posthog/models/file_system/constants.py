from django.db.models import Q

# The product surface a FileSystem row belongs to. Legacy rows predate this column and are
# stored as NULL; they are read as the default ("web"). New rows always store an explicit value.
DEFAULT_SURFACE = "web"

# Types of retired products. Their rows can stay in the database, but they have no backing model and
# no page to open. The tree hides them, and a delete removes only the row.
RETIRED_FILE_SYSTEM_TYPES: frozenset[str] = frozenset({"link"})


def surface_q(surface: str) -> Q:
    """Build the read filter for a surface. The default surface also matches legacy NULL rows."""
    if surface == DEFAULT_SURFACE:
        return Q(surface__isnull=True) | Q(surface=DEFAULT_SURFACE)
    return Q(surface=surface)
