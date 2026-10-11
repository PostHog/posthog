from typing import Any

from .harmonic_company import describes_company, dict_field, harmonic_headcount, traction_latest, website_domain

# Account.Industry picklist values, read from the Salesforce org on 2026-10-09. The picklist is not restricted, so
# Salesforce accepts any string. Writes are held to these values to keep stray spellings out of the field.
INDUSTRY_PICKLIST = frozenset(
    {
        "Aerospace & Defense",
        "Agriculture",
        "Air Freight & Logistics",
        "Apparel",
        "Automotive",
        "Banking",
        "Beverages",
        "Biotechnology",
        "Capital Markets",
        "Chemicals",
        "Commercial Services & Supplies",
        "Communications",
        "Construction",
        "Construction & Engineering",
        "Consulting",
        "Consumer Services",
        "Distributors",
        "Diversified Consumer Services",
        "Diversified Financial Services",
        "Diversified Telecommunication Services",
        "Education",
        "Education Services",
        "Electrical Equipment",
        "Electronics",
        "Energy",
        "Engineering",
        "Entertainment",
        "Environmental",
        "Family Services",
        "Finance",
        "Food & Beverage",
        "Food & Staples Retailing",
        "Food Products",
        "Government",
        "Health Care Equipment & Supplies",
        "Health Care Providers & Services",
        "Hospitality",
        "Hotels, Restaurants & Leisure",
        "IT Services",
        "Industrial Conglomerates",
        "Industrials",
        "Insurance",
        "Internet Software & Services",
        "Leisure Products",
        "Life Sciences Tools & Services",
        "Machinery",
        "Manufacturing",
        "Media",
        "Not For Profit",
        "Other",
        "Paper & Forest Products",
        "Personal Products",
        "Pharmaceuticals",
        "Professional Services",
        "Real Estate",
        "Recreation",
        "Retail",
        "Retailing",
        "Road & Rail",
        "Semiconductors & Semiconductor Equipment",
        "Shipping",
        "Software",
        "Specialized Consumer Services",
        "Specialty Retail",
        "Technology",
        "Telecommunications",
        "Textiles, Apparel & Luxury Goods",
        "Transportation",
        "Utilities",
        "Wireless Telecommunication Services",
    }
)

# Harmonic tag spellings, lowercased, and the picklist value each one maps to.
INDUSTRY_ALIASES: dict[str, str] = {
    "artificial intelligence": "Software",
    "ai / ml": "Software",
    "ai/ml": "Software",
    "developer tools": "Software",
    "developer operations & ai building tools": "Software",
    "business software services": "Software",
    "enterprise productivity & automation": "Software",
    "saas": "Software",
    "software development": "Software",
    "fintech": "Finance",
    "financial services": "Finance",
    "healthtech": "Health Care Providers & Services",
    "healthcare": "Health Care Providers & Services",
    "e-commerce": "Retailing",
    "ecommerce": "Retailing",
    "edtech": "Education Services",
    "cybersecurity": "Software",
    "information technology": "IT Services",
    "internet": "Internet Software & Services",
    "web services": "Internet Software & Services",
    "biotech": "Biotechnology",
    "crypto": "Capital Markets",
    "blockchain": "Capital Markets",
    "gaming": "Entertainment",
    "gaming & interactive entertainment": "Entertainment",
    "logistics": "Air Freight & Logistics",
    "real estate": "Real Estate",
    "consumer": "Diversified Consumer Services",
    "hardware": "Electronics",
    "robotics": "Machinery",
    "semiconductors": "Semiconductors & Semiconductor Equipment",
    "telecommunications": "Telecommunications",
    "media": "Media",
    "digital media & content platforms": "Media",
    "insurance": "Insurance",
    "legaltech": "Professional Services",
    "hrtech": "Professional Services",
    "marketplace": "Internet Software & Services",
}

# Industries that describe whom a company sells to as readily as what it does. A company that builds software for
# banks carries a finance tag, so a tag that maps to one of these names the industry only when no other tag maps.
SECTOR_INDUSTRIES = frozenset({"Finance", "Banking", "Insurance", "Capital Markets", "Diversified Financial Services"})

# Account.Company_LinkedIn__c is a URL(255) field. Salesforce rejects the whole record for a longer value.
LINKEDIN_URL_MAX_LENGTH = 255

LINKEDIN_COUNT_FIELDS = ("LinkedIn_Engineer_Count__c", "LinkedIn_Rolecount__c")


def _map_industry(tag: str) -> str | None:
    if tag in INDUSTRY_PICKLIST:
        return tag
    return INDUSTRY_ALIASES.get(tag.lower())


def _tags(company: dict[str, Any], key: str) -> list[dict[str, Any]]:
    tags = company.get(key)
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, dict)]


def _tag_values(company: dict[str, Any]) -> list[str]:
    legacy = sorted(_tags(company, "tags"), key=lambda tag: not tag.get("isPrimaryTag"))
    newer = _tags(company, "tagsV2")
    return [tag["displayValue"] for tag in legacy + newer if isinstance(tag.get("displayValue"), str)]


def account_industry(company: dict[str, Any]) -> str | None:
    """The Account.Industry picklist value for a company, or None when no tag maps to one.

    Harmonic has no industry field, so its tags stand in. The legacy tags name the product more often than the
    newer sector-led ones, so they come first, led by the tag Harmonic marks as primary.
    """
    mapped = [industry for tag in _tag_values(company) if (industry := _map_industry(tag)) is not None]
    for industry in mapped:
        if industry not in SECTOR_INDUSTRIES:
            return industry
    return mapped[0] if mapped else None


def _total_funding(company: dict[str, Any]) -> Any:
    total = dict_field(company, "funding").get("fundingTotal")
    if total == 0 and not describes_company(company):
        return None
    return total


def _founded_year(company: dict[str, Any]) -> int | None:
    date = dict_field(company, "foundingDate").get("date")
    if not isinstance(date, str) or "-" not in date:
        return None
    try:
        return int(date.split("-")[0])
    except ValueError:
        return None


def _linkedin_url(company: dict[str, Any], queried_domain: str) -> str | None:
    # Harmonic can return a record whose facts fit the queried company while its web identity belongs to another
    # company. The LinkedIn page is written only when the website Harmonic reports is on the queried domain.
    if website_domain(company) != queried_domain:
        return None
    url = dict_field(dict_field(company, "socials"), "linkedin").get("url")
    return url if isinstance(url, str) and 0 < len(url) <= LINKEDIN_URL_MAX_LENGTH else None


def _linkedin_headcounts(company: dict[str, Any]) -> dict[str, int | float]:
    # The pct_engineers__c formula divides the engineer count by the role count, so the two are written only as a
    # pair. One fresh count beside a stale one produces a ratio that neither source reported, and a role count of
    # zero makes the formula divide by zero.
    engineering = traction_latest(company, "headcountEngineering")
    total = traction_latest(company, "headcount")
    if engineering is None or total is None or total <= 0:
        return {}
    return {"LinkedIn_Engineer_Count__c": engineering, "LinkedIn_Rolecount__c": total}


def overwritten_account_fields(company: dict[str, Any]) -> dict[str, Any]:
    """The canonical Account fields that always take Harmonic's value."""
    fields = {
        "Total_Funding__c": _total_funding(company),
        "Last_Funding_Date__c": dict_field(company, "funding").get("lastFundingAt"),
        "Founded_year__c": _founded_year(company),
    }
    return {field: value for field, value in fields.items() if value is not None}


def fill_only_account_fields(company: dict[str, Any], *, queried_domain: str) -> dict[str, Any]:
    """The canonical Account fields that take Harmonic's value only while the Account holds none.

    Other writers also set these fields, and a different value from Harmonic is not evidence that theirs is wrong.
    Pass the result through unoccupied_fields() with the Account's current values before it is written.
    """
    fields = {
        "NumberOfEmployees": harmonic_headcount(company),
        "Industry": account_industry(company),
        "Company_LinkedIn__c": _linkedin_url(company, queried_domain),
        **_linkedin_headcounts(company),
    }
    return {field: value for field, value in fields.items() if value is not None}


def unoccupied_fields(fill_fields: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    """The fill-only fields that the Account's current values leave room for.

    A field that the Account read did not return is unknown, not empty, and is not written.
    """
    fields = {field: value for field, value in fill_fields.items() if field in account and account[field] in (None, "")}
    if not all(field in fields for field in LINKEDIN_COUNT_FIELDS):
        for field in LINKEDIN_COUNT_FIELDS:
            fields.pop(field, None)
    return fields
