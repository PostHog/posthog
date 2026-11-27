"""One page, whatever tracking parameters an engine added to its link.

Engines append parameters such as `?utm_source=openai` to the links they cite, so the same page arrives
under several URLs. The reads that rank or compare pages group by the URL without them, in SQL, so an
answer that cites two of the variants still counts once. `page_url` is the same rule in Python, for a URL
a person picked from a report.
"""

from __future__ import annotations

import re

# Parameters that only say where a click came from. Parameters that pick the content, such as `?id=` or
# `?page=`, stay, so two different pages never merge.
_TRACKING_PARAMS = (
    r"utm_[^=&#]*|gclid|gbraid|wbraid|dclid|fbclid|msclkid|yclid|igshid|srsltid|mc_cid|mc_eid|_hsenc|_hsmi"
)

_PARAM = re.compile(rf"([?&])(?:{_TRACKING_PARAMS})(?:=[^&#]*)?(?=[&#]|$)", re.IGNORECASE)
_REPEATED_SEPARATOR = re.compile(r"([?&])&+")
_TRAILING_SEPARATOR = re.compile(r"[?&]+(#|$)")


def page_url(url: str) -> str:
    """The URL without its tracking parameters. Mirrors `page_url_sql`."""
    without = _PARAM.sub(r"\1", url)
    return _TRAILING_SEPARATOR.sub(r"\1", _REPEATED_SEPARATOR.sub(r"\1", without), count=1)


def page_url_sql(column: str) -> str:
    """The Postgres expression for `page_url` of a column. `column` is a trusted SQL identifier, never input."""
    without = rf"regexp_replace({column}, '([?&])(?:{_TRACKING_PARAMS})(?:=[^&#]*)?(?=[&#]|$)', '\1', 'gi')"
    collapsed = rf"regexp_replace({without}, '([?&])&+', '\1', 'g')"
    return rf"regexp_replace({collapsed}, '[?&]+(#|$)', '\1')"
