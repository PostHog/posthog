from collections.abc import Iterable


def resolve_entity_name(entity: str, entity_names: Iterable[str]) -> str | None:
    """
    Match a caller's entity name to one of the taxonomy's own names, or return None.

    The taxonomy names an entity in the singular, but a query reads the plural table it lives in
    (`sessions`, `persons`), so a caller that starts from the query asks about `sessions`. That
    name says exactly which entity it wants, so answer it instead of spending a round trip on a
    rejection.

    A trailing `s` is dropped only when what remains is a name the taxonomy has, which keeps a
    group type whose own name ends in `s` resolving to itself.
    """
    candidate = entity.strip().lower()
    by_name = {name.lower(): name for name in entity_names}
    if candidate in by_name:
        return by_name[candidate]
    return by_name.get(candidate.removesuffix("s"))
