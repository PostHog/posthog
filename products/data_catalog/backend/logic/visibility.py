"""Who may see which metric.

Catalog viewer access decides whether a caller sees the catalog at all; this module decides which
metrics survive that check, given the tables the caller cannot read. Every surface that lists metrics
shares it, so `system.information_schema.metrics` and a prompt-side listing cannot disagree about
what a caller is allowed to know exists.
"""

from typing import Optional


def references_denied_table(referenced_table_names: Optional[list[str]], denied: set[str]) -> bool:
    """Whether any of a metric's referenced tables is in the caller's denied set.

    `referenced_table_names` stores the surface identifier the author typed (bare `charges` or dotted
    `stripe.charges`, any case), while `_denied_tables` holds a mix of bare names, lowercased
    qualified warehouse keys, and `system.<name>`. Match case-insensitively and by leaf so a
    qualified reference to a bare-denied table (or the reverse) still trips the denial — err toward
    hiding rather than leaking a metric whose source the caller cannot read.
    """
    if not denied or not referenced_table_names:
        return False
    denied_norm = {name.lower() for name in denied}
    denied_norm |= {name.rsplit(".", 1)[-1] for name in denied_norm}
    for name in referenced_table_names:
        normalized = name.lower()
        if normalized in denied_norm or normalized.rsplit(".", 1)[-1] in denied_norm:
            return True
    return False
