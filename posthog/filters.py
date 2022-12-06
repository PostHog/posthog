from typing import List, Optional, Tuple


def term_search_filter_sql(search_fields: List[str], search_terms: Optional[str] = "") -> Tuple[str, dict]:
    if not search_fields or not search_terms:
        return "", {}

    terms = list(filter(None, search_terms.replace("\x00", "").split(" ")))

    kwargs = {}
    term_filter = []
    for term_idx, search_term in enumerate(terms):
        search_filter_query = []
        for idx, search_field in enumerate(search_fields):
            index = term_idx * len(search_fields) + idx
            search_filter_query.append(f"{search_field} ilike %(search_{index})s")
            kwargs[f"search_{index}"] = f"%{search_term}%"
        term_filter.append(f"({' OR '.join(search_filter_query)})")

    if term_filter:
        return f"AND ({' AND '.join(term_filter)})", kwargs
    else:
        return "", {}
