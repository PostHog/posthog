from collections.abc import Iterable


def resolve_entity_name(entity: str, entity_names: Iterable[str]) -> str | None:
    """
    Match a caller's entity name to one of the taxonomy's own names, or return None.

    The taxonomy names an entity in the singular, but a query reads the plural table it lives in,
    so a caller that starts from the query asks about `sessions`.
    """
    candidate = entity.strip().lower()
    by_name = {name.lower(): name for name in entity_names}
    if candidate in by_name:
        return by_name[candidate]
    return by_name.get(candidate.removesuffix("s"))
