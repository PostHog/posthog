from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from ee.billing.salesforce_enrichment.account_fields import (
    account_industry,
    fill_only_account_fields,
    overwritten_account_fields,
    unoccupied_fields,
)
from ee.billing.salesforce_enrichment.constants import ACCOUNT_FILL_FIELDS

DOMAIN = "example.com"


def _tag(value: str, primary: bool = False) -> dict[str, Any]:
    return {"displayValue": value, "isPrimaryTag": primary}


def _company(**overrides: Any) -> dict[str, Any]:
    company: dict[str, Any] = {
        "name": "Example Corp",
        "headcount": 120,
        "website": {"url": "https://example.com", "domain": "example.com"},
        "socials": {"linkedin": {"url": "https://www.linkedin.example/company/example-corp"}},
        "tractionMetrics": {
            "headcount": {"latestMetricValue": 118},
            "headcountEngineering": {"latestMetricValue": 40},
        },
        "tags": [_tag("Software", primary=True)],
        "funding": {"fundingTotal": 5000000, "lastFundingAt": "2025-02-25T00:00:00Z"},
        "foundingDate": {"date": "2015-03-01T00:00:00Z"},
    }
    company.update(overrides)
    return company


def _fields(company: dict[str, Any], account: dict[str, Any] | None = None) -> dict[str, Any]:
    fill_fields = fill_only_account_fields(company, queried_domain=DOMAIN)
    return {**overwritten_account_fields(company), **unoccupied_fields(fill_fields, {"Id": "001X", **(account or {})})}


class TestAccountIndustry(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "primary_legacy_tag_leads",
                {"tags": [_tag("Retail"), _tag("Software", primary=True)]},
                "Software",
            ),
            (
                "legacy_tags_before_tags_v2",
                {"tags": [_tag("Retail")], "tagsV2": [_tag("Software")]},
                "Retail",
            ),
            (
                "sector_industry_loses_to_another_mapped_tag",
                {"tags": [_tag("Financial Services", primary=True)], "tagsV2": [_tag("AI / ML")]},
                "Software",
            ),
            (
                "sector_industry_wins_when_alone",
                {"tags": [_tag("Insurance", primary=True), _tag("Unmapped Thing")]},
                "Insurance",
            ),
            ("no_tag_maps", {"tags": [_tag("Unmapped Thing")], "tagsV2": [_tag("Other Unmapped")]}, None),
            ("alias_is_case_insensitive", {"tags": [_tag("AI / Ml")]}, "Software"),
            ("tag_that_is_not_a_record_is_skipped", {"tags": [None, _tag("SaaS")]}, "Software"),
        ]
    )
    def test_account_industry(self, _name, company, expected):
        assert account_industry(company) == expected


class TestCanonicalAccountFields(SimpleTestCase):
    @parameterized.expand(
        [
            ("employees_none", "NumberOfEmployees", None, True, 120),
            ("employees_empty_string", "NumberOfEmployees", "", True, 120),
            ("employees_occupied", "NumberOfEmployees", 7, False, None),
            (
                "linkedin_url_none",
                "Company_LinkedIn__c",
                None,
                True,
                "https://www.linkedin.example/company/example-corp",
            ),
            ("linkedin_url_occupied", "Company_LinkedIn__c", "https://other.example/page", False, None),
            ("industry_empty", "Industry", None, True, "Software"),
            ("industry_outside_picklist", "Industry", "Software Development", False, None),
            ("industry_in_picklist", "Industry", "Retail", False, None),
        ]
    )
    def test_fill_rule_follows_the_current_value(self, _name, field, current, written, expected):
        fields = _fields(_company(), {field: current})
        if written:
            assert fields[field] == expected
        else:
            assert field not in fields

    @parameterized.expand([("NumberOfEmployees",), ("Company_LinkedIn__c",), ("Industry",)])
    def test_field_not_read_is_unknown_not_empty(self, field):
        assert field not in _fields(_company(), {})

    @parameterized.expand(
        [
            ("both_empty", {"LinkedIn_Engineer_Count__c": None, "LinkedIn_Rolecount__c": ""}, True),
            ("engineer_count_occupied", {"LinkedIn_Engineer_Count__c": 5, "LinkedIn_Rolecount__c": None}, False),
            ("role_count_occupied", {"LinkedIn_Engineer_Count__c": None, "LinkedIn_Rolecount__c": 50}, False),
            ("one_side_not_read", {"LinkedIn_Engineer_Count__c": None}, False),
        ]
    )
    def test_linkedin_counts_are_written_only_as_an_empty_pair(self, _name, account, written):
        fields = _fields(_company(), account)
        if written:
            assert fields["LinkedIn_Engineer_Count__c"] == 40
            assert fields["LinkedIn_Rolecount__c"] == 118
        else:
            assert "LinkedIn_Engineer_Count__c" not in fields
            assert "LinkedIn_Rolecount__c" not in fields

    @parameterized.expand(
        [
            ("missing_engineering", {"headcount": {"latestMetricValue": 118}}),
            ("missing_total", {"headcountEngineering": {"latestMetricValue": 40}}),
            ("zero_total", {"headcount": {"latestMetricValue": 0}, "headcountEngineering": {"latestMetricValue": 0}}),
        ]
    )
    def test_linkedin_counts_need_both_traction_metrics(self, _name, traction):
        fields = _fields(
            _company(tractionMetrics=traction),
            {"LinkedIn_Engineer_Count__c": None, "LinkedIn_Rolecount__c": None},
        )
        assert "LinkedIn_Engineer_Count__c" not in fields
        assert "LinkedIn_Rolecount__c" not in fields

    @parameterized.expand(
        [
            ("zero_without_name", {"name": None}, 0, False),
            ("zero_without_headcount", {"headcount": None, "tractionMetrics": {}}, 0, False),
            ("zero_with_zero_headcount", {"headcount": 0, "tractionMetrics": {}}, 0, False),
            ("zero_with_name_and_headcount", {}, 0, True),
            ("positive_without_name", {"name": None}, 250000, True),
            ("positive_without_headcount", {"headcount": None, "tractionMetrics": {}}, 250000, True),
        ]
    )
    def test_total_funding_zero_is_written_only_for_a_described_company(self, _name, overrides, total, written):
        company = _company(funding={"fundingTotal": total}, **overrides)
        fields = _fields(company)
        if written:
            assert fields["Total_Funding__c"] == total
        else:
            assert "Total_Funding__c" not in fields

    @parameterized.expand(
        [
            ("company_headcount", {"headcount": 120}, 120),
            (
                "traction_fallback",
                {"headcount": None, "tractionMetrics": {"headcount": {"latestMetricValue": 118}}},
                118,
            ),
            (
                "traction_fallback_for_a_zero_headcount",
                {"headcount": 0, "tractionMetrics": {"headcount": {"latestMetricValue": 118}}},
                118,
            ),
        ]
    )
    def test_number_of_employees_source(self, _name, overrides, expected):
        assert _fields(_company(**overrides), {"NumberOfEmployees": None})["NumberOfEmployees"] == expected

    def test_every_fill_only_field_is_read_before_the_write(self):
        assert set(fill_only_account_fields(_company(), queried_domain=DOMAIN)) == set(ACCOUNT_FILL_FIELDS)

    def test_zero_headcount_is_not_written(self):
        company = _company(headcount=0, tractionMetrics={"headcount": {"latestMetricValue": 0}})
        assert "NumberOfEmployees" not in _fields(company, {"NumberOfEmployees": None})

    @parameterized.expand(
        [
            ("same_domain", {"domain": "example.com"}, True),
            ("www_and_case_ignored", {"domain": "WWW.Example.com"}, True),
            ("other_domain", {"domain": "example.org"}, False),
            ("no_domain", {}, False),
        ]
    )
    def test_linkedin_url_needs_the_queried_domain(self, _name, website, written):
        fields = _fields(_company(website=website), {"Company_LinkedIn__c": None})
        assert ("Company_LinkedIn__c" in fields) is written

    @parameterized.expand([("at_limit", 255, True), ("over_limit", 256, False)])
    def test_linkedin_url_length_limit(self, _name, length, written):
        url = "https://www.linkedin.example/" + "a" * (length - len("https://www.linkedin.example/"))
        company = _company(socials={"linkedin": {"url": url}})
        assert ("Company_LinkedIn__c" in _fields(company, {"Company_LinkedIn__c": None})) is written

    @parameterized.expand(
        [
            ("year_precision_date", {"date": "1983-01-01T00:00:00Z"}, 1983),
            ("malformed_date", {"date": "not-a-date"}, None),
            ("missing_date", {}, None),
        ]
    )
    def test_founded_year(self, _name, founding_date, expected):
        fields = _fields(_company(foundingDate=founding_date))
        if expected is None:
            assert "Founded_year__c" not in fields
        else:
            assert fields["Founded_year__c"] == expected
