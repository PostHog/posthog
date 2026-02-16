REDIS_TTL_SECONDS: int = 12 * 60 * 60  # 12h
SALESFORCE_ACCOUNTS_CACHE_KEY: str = "salesforce-enrichment:global:all_accounts"
SALESFORCE_ORG_MAPPINGS_CACHE_KEY: str = "salesforce-enrichment:global:org_mappings"
HARMONIC_BASE_URL: str = "https://api.harmonic.ai"
YC_INVESTOR_NAME: str = "y combinator"
HARMONIC_DEFAULT_MAX_CONCURRENT_REQUESTS: int = 5  # rate limit: 10/s
HARMONIC_REQUEST_TIMEOUT_SECONDS: int = 30
HARMONIC_BATCH_SIZE: int = 100
HARMONIC_DOMAIN_VARIATIONS: list[str] = ["", "www."]  # Try exact domain first, then with www prefix
SALESFORCE_UPDATE_BATCH_SIZE: int = 200  # Max records per sObject Collections API call
DEFAULT_CHUNK_SIZE: int = 5000

# Harmonic GraphQL query for company enrichment
HARMONIC_COMPANY_ENRICHMENT_QUERY = """
mutation($identifiers: CompanyEnrichmentIdentifiersInput!) {
    enrichCompanyByIdentifiers(identifiers: $identifiers) {
        companyFound
        company {
            name
            companyType
            website {
                url
                domain
            }
            headcount
            description
            location {
                city
                country
                state
            }
            foundingDate {
                date
                granularity
            }
            funding {
                fundingTotal
                numFundingRounds
                lastFundingAt
                lastFundingType
                lastFundingTotal
                fundingStage
                investors {
                    ... on Company {
                        name
                    }
                    ... on Person {
                        fullName
                    }
                }
            }
            tractionMetrics {
                webTraffic {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                linkedinFollowerCount {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                twitterFollowerCount {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                headcount {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                headcountEngineering {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
            }
            tags {
                type
                displayValue
                dateAdded
                isPrimaryTag
            }
            tagsV2 {
                type
                displayValue
                dateAdded
            }
        }
    }
}
"""

# Salesforce query for accounts with websites
SALESFORCE_ACCOUNTS_QUERY = """
    SELECT Id, Name, Website, CreatedDate
    FROM Account
    WHERE Website != null
    ORDER BY CreatedDate DESC
"""

METRIC_PERIODS = {"90d": 90, "180d": 180}

# PostHog usage enrichment constants
POSTHOG_ORG_ID_FIELD = "Posthog_Org_ID__c"
POSTHOG_USAGE_ENRICHMENT_BATCH_SIZE = 100

# Salesforce field mappings for PostHog usage signals
# Format: internal_field_name -> salesforce_custom_field_name
POSTHOG_USAGE_FIELD_MAPPINGS = {
    # Events-based metrics (7-day)
    "total_events_7d": "posthog_total_events_7d__c",
    "events_avg_daily_7d": "posthog_events_avg_daily_7d__c",
    "products_activated_7d": "posthog_products_7d__c",
    "events_7d_momentum": "posthog_events_7d_momentum__c",
    # Events-based metrics (30-day)
    "total_events_30d": "posthog_total_events_30d__c",
    "events_avg_daily_30d": "posthog_events_avg_daily_30d__c",
    "products_activated_30d": "posthog_products_30d__c",
    "events_30d_momentum": "posthog_events_30d_momentum__c",
}

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "protonmail.com",
    "zoho.com",
    "yandex.com",
    "live.com",
    "msn.com",
    "me.com",
    "mac.com",
    "gmx.com",
    "yahoo.co.uk",
    "yahoo.co.jp",
    "yahoo.co.in",
    "yahoo.com.au",
    "yahoo.com.sg",
    "yahoo.com.ph",
    "yahoo.com.my",
    "yahoo.com.hk",
    "yahoo.com.tw",
    "yahoo.com.vn",
    "yahoo.com.br",
    "yahoo.com.ar",
    "yahoo.com.mx",
    "yahoo.com.tr",
    "yahoo.com.ua",
    "yahoo.com.eg",
    "yahoo.com.sa",
    "yahoo.com.ae",
    "yahoo.com.kr",
    "yahoo.com.cn",
    "yahoo.com.ru",
    "yahoo.com.id",
    "yahoo.com.th",
    "yahoo.com.ve",
    "yahoo.com.pe",
    "yahoo.com.cl",
    "yahoo.com.co",
    "yahoo.com.ec",
    "yahoo.com.uy",
    "yahoo.com.py",
    "yahoo.com.bo",
    "yahoo.com.do",
    "yahoo.com.pr",
    "yahoo.com.gt",
    "yahoo.com.sv",
    "yahoo.com.hn",
    "yahoo.com.ni",
    "yahoo.com.cr",
    "yahoo.com.pa",
}
