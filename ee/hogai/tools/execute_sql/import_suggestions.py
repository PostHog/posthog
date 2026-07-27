"""Map a missing HogQL table to a data-warehouse source the user could import.

When an ``execute_sql`` query references a table that doesn't exist, it's often a moment where the
user needs external business data (revenue, CRM, support tickets, …) that hasn't been imported yet.
This builds a short, additive hint pointing the agent at ``data-warehouse-source-setup`` so the
"missing table → import a source" path actually fires instead of dead-ending on the error.
"""

import re

# (table-name keywords, candidate source types, human label). First-match-wins per category, but a
# table can match multiple categories (e.g. "customers" is both revenue and CRM) — all are surfaced.
_SOURCE_KEYWORDS: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
    (
        ("charge", "subscription", "invoice", "payment", "payout", "refund", "revenue", "mrr", "transaction"),
        ("Stripe", "Chargebee"),
        "revenue and payments",
    ),
    (
        ("customer", "contact", "deal", "company", "lead", "opportunity", "crm"),
        ("Hubspot", "Salesforce"),
        "CRM and sales",
    ),
    (("ticket", "support", "helpdesk", "conversation"), ("Zendesk",), "support tickets"),
    (
        ("campaign", "adgroup", "ad_group", "impression", "spend", "ads", "marketing"),
        ("GoogleAds", "MetaAds"),
        "ads and marketing",
    ),
    (("order", "product", "cart", "checkout", "fulfillment", "shop"), ("Shopify", "BigCommerce"), "e-commerce"),
]

_UNKNOWN_TABLE_RE = re.compile(r"[Uu]nknown table `([^`]+)`")


def extract_unknown_tables(error_message: str) -> list[str]:
    """Pull the table name(s) out of a HogQL ``Unknown table `x`.`` error message."""
    return list(dict.fromkeys(_UNKNOWN_TABLE_RE.findall(error_message)))


def _strip_prefix(table: str) -> str:
    # Imported tables are usually prefixed (e.g. `stripe_charges`); match on the trailing part too.
    return table.split("_", 1)[1] if "_" in table else table


def suggest_sources_for_table(table: str) -> list[tuple[tuple[str, ...], str]]:
    """Return (candidate_source_types, label) tuples whose keywords match the table name."""
    name = table.lower()
    bare = _strip_prefix(name)
    matches: list[tuple[tuple[str, ...], str]] = []
    for keywords, sources, label in _SOURCE_KEYWORDS:
        if any(kw in name or kw in bare for kw in keywords):
            matches.append((sources, label))
    return matches


def build_import_suggestion(missing_tables: list[str], existing_source_types: set[str]) -> str | None:
    """Build an additive hint suggesting a warehouse source for unimported tables.

    ``existing_source_types`` lets us avoid suggesting a source the team already connected (the data
    may simply be under a different prefix). Returns ``None`` when nothing useful can be suggested.
    """
    if not missing_tables:
        return None

    suggested: list[str] = []
    seen: set[str] = set()
    for table in missing_tables:
        for sources, label in suggest_sources_for_table(table):
            fresh = [s for s in sources if s not in existing_source_types]
            key = f"{label}:{','.join(sources)}"
            if not fresh or key in seen:
                continue
            seen.add(key)
            suggested.append(f"- {label}: connect {' or '.join(fresh)}")

    lines = [
        "<data_import_suggestion>",
        "One or more referenced tables don't exist yet. If you're after external business data that "
        "hasn't been imported, set up a data warehouse source with the 'data-warehouse-source-setup' "
        "tool (it validates credentials, discovers tables, and creates the source in one step). For "
        "credentialed sources, prefer the secure connect-link handoff over pasting secrets.",
    ]
    if suggested:
        lines.append("Likely matches for the missing table(s):")
        lines.extend(suggested)
    else:
        lines.append(
            "If this is data from your own database, connect a Postgres, MySQL, BigQuery, or Snowflake source."
        )
    if existing_source_types:
        lines.append(
            "Note: the team already has these source types connected — the data may be under a "
            f"different table prefix: {', '.join(sorted(existing_source_types))}. "
            "Check 'external-data-sources-list' before importing again."
        )
    lines.append("</data_import_suggestion>")
    return "\n".join(lines)
