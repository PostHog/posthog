"""One page, whatever tracking parameters an engine added to its link.

Engines append parameters such as `?utm_source=openai` to the links they cite, so the same page arrives
under several URLs. The reads that rank or compare pages group by the URL without them, in SQL, so an
answer that cites two of the variants still counts once. `page_url` is the same rule in Python, for a URL
a person picked from a report.

Only the query component changes. The scheme, host, path and fragment stay as the engine wrote them, so a
`&trk=` inside a path or a host never merges two different pages or points a link at another host.
"""

from __future__ import annotations

import re

# Parameters that only say where a click came from. Parameters that pick the content, such as `?id=` or
# `?page=`, stay, so two different pages never merge.
_TRACKING_KEYS = (
    r"utm_[^=]*|gclid|gbraid|wbraid|dclid|fbclid|msclkid|yclid|igshid|srsltid|mc_cid|mc_eid|_hsenc|_hsmi|trk"
)
_TRACKING_PARAM = re.compile(rf"^(?:{_TRACKING_KEYS})(?:=|$)", re.IGNORECASE)
# The query runs from the first `?` before any `#` to the first `#`.
_PARTS = re.compile(r"^([^?#]*)(?:\?([^#]*))?(#.*)?$", re.DOTALL)


def page_url(url: str) -> str:
    """The URL without its tracking parameters. Mirrors `page_url_sql`."""
    match = _PARTS.match(url)
    if match is None:
        return url
    before, query, fragment = match.group(1), match.group(2), match.group(3)
    if query is None:
        return url
    kept = "&".join(param for param in query.split("&") if param and not _TRACKING_PARAM.match(param))
    return before + (f"?{kept}" if kept else "") + (fragment or "")


def page_url_sql(column: str) -> str:
    """The Postgres expression for `page_url` of a column. `column` is a trusted SQL identifier, never input."""
    query = rf"substring({column} from '^[^?#]*\?([^#]*)')"
    kept = (
        rf"array_to_string(ARRAY(SELECT param FROM unnest(string_to_array({query}, '&')) WITH ORDINALITY AS q(param, n)"
        rf" WHERE param <> '' AND param !~* '^(?:{_TRACKING_KEYS})(?:=|$)' ORDER BY n), '&')"
    )
    return (
        rf"CASE WHEN {query} IS NULL THEN {column} ELSE substring({column} from '^[^?#]*')"
        rf" || CASE WHEN {kept} <> '' THEN '?' || {kept} ELSE '' END"
        rf" || coalesce(substring({column} from '#.*$'), '') END"
    )
