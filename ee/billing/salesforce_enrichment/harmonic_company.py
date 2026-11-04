import re
from typing import Any
from urllib.parse import urlparse

# ISO 639-1 language codes.
_LANGUAGE_CODES = frozenset(
    (
        "aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el "
        "en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it "
        "iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt "
        "my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg sh si sk "
        "sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi "
        "yo za zh zu"
    ).split()
)

# ISO 3166-1 alpha-2 country codes. A site can put the landing page for one country under its code, as in "/us".
_COUNTRY_CODES = frozenset(
    (
        "ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by "
        "bz ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg eh er es et fi fj fk "
        "fm fo fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir "
        "is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk "
        "ml mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm "
        "pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz tc td tf "
        "tg th tj tk tl tm tn to tr tt tv tw tz ua ug um us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw"
    ).split()
)

# A path segment whose first subtag is in neither set, such as a product page, is not a locale.
_LOCALE_PREFIXES = _LANGUAGE_CODES | _COUNTRY_CODES

# A language or country code, then an optional language, script or region, then an optional region: "en", "us",
# "de-at", "us-en", "zh-Hant", "zh-Hant-TW", "es-419".
_LOCALE_SEGMENT = re.compile(r"^([a-z]{2})(?:[-_][a-z]{2,4})?(?:[-_](?:[a-z]{2}|\d{3}))?$", re.IGNORECASE)
_INDEX_FILE = re.compile(r"^(index|default|home)\.[a-z]+$", re.IGNORECASE)


def _is_locale(segment: str) -> bool:
    match = _LOCALE_SEGMENT.match(segment)
    return match is not None and match.group(1).lower() in _LOCALE_PREFIXES


def website_path_is_root(url: str) -> bool:
    """Whether a website URL points at the root of its site.

    A lone language or country segment, or an index file, is still the root, because a localized landing page
    belongs to the company itself. A URL that cannot be parsed counts as the root, so that a record is never rejected
    on a guess.
    """
    try:
        path = urlparse(url if "://" in url else f"https://{url}").path
    except ValueError:
        return True
    segments = [segment for segment in path.split("/") if segment]
    if segments and _INDEX_FILE.match(segments[-1]):
        segments.pop()
    return not segments or (len(segments) == 1 and _is_locale(segments[0]))


def dict_field(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    return value if isinstance(value, dict) else {}


def is_sub_entity(company: dict[str, Any]) -> bool:
    """Whether Harmonic answered a domain lookup with a different entity that lives under that domain.

    Harmonic keys an entity on its website. A ventures arm, a school within a university, or one product of a
    platform has a page under the parent's domain as its website, and a lookup of the parent's domain can return
    it. Its name, headcount and funding do not describe the parent.
    """
    url = dict_field(company, "website").get("url")
    return isinstance(url, str) and bool(url) and not website_path_is_root(url)


def traction_latest(company: dict[str, Any], metric: str) -> int | float | None:
    latest = dict_field(dict_field(company, "tractionMetrics"), metric).get("latestMetricValue")
    return latest if isinstance(latest, int | float) else None


def harmonic_headcount(company: dict[str, Any]) -> int | None:
    """The company's current headcount, from the company record or else the latest traction reading.

    Harmonic can report zero where it has no reading, so only a positive count is a headcount.
    """
    for count in (company.get("headcount"), traction_latest(company, "headcount")):
        if isinstance(count, int | float) and count > 0:
            return int(count)
    return None


def describes_company(company: dict[str, Any]) -> bool:
    """Whether the record names and sizes a company.

    Harmonic can report a company as found and return a record with almost no facts. Zero funding on such a record
    means that Harmonic has no data, not that the company raised nothing.
    """
    name = company.get("name")
    return isinstance(name, str) and bool(name) and harmonic_headcount(company) is not None


def website_domain(company: dict[str, Any]) -> str | None:
    """The domain Harmonic reports for the company's website, lowercased and without a www prefix."""
    domain = dict_field(company, "website").get("domain")
    if not isinstance(domain, str):
        return None
    return domain.lower().strip().removeprefix("www.") or None
