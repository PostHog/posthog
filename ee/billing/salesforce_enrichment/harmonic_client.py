import json
import os
import requests
from datetime import datetime
from django.conf import settings


class HarmonicClient:
    """
    Simple Harmonic API client for company enrichment.
    """

    def __init__(self):
        self.api_key = settings.HARMONIC_API_KEY

        if not self.api_key:
            raise ValueError("Missing Harmonic API key: HARMONIC_API_KEY")

        self.base_url = settings.HARMONIC_BASE_URL

        # Setup logging directory
        self.log_dir = os.path.join(os.path.dirname(__file__), "harmonic_api_logs")
        os.makedirs(self.log_dir, exist_ok=True)

    def _save_api_response(self, domain: str, response_data: dict, is_error: bool = False):
        """Save API response to a local file for debugging and analysis."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_domain = domain.replace(".", "_").replace("/", "_")
        status = "error" if is_error else "success"

        filename = f"{timestamp}_{safe_domain}_{status}.json"
        filepath = os.path.join(self.log_dir, filename)

        log_data = {
            "timestamp": datetime.now().isoformat(),
            "domain": domain,
            "status": status,
            "response": response_data,
        }

        with open(filepath, "w") as f:
            json.dump(log_data, f, indent=2, default=str)

        return filepath

    def get_company_by_domain(self, domain: str):
        """Get company data using simple REST API."""
        # Clean domain
        domain = domain.lower().strip()
        if domain.startswith("http://"):
            domain = domain[7:]
        if domain.startswith("https://"):
            domain = domain[8:]
        if domain.startswith("www."):
            domain = domain[4:]

        url = f"{self.base_url}/companies"
        params = {"website_domain": domain, "apikey": self.api_key}

        response = requests.get(url, params=params)
        response.raise_for_status()

        return response.json()

    def enrich_company_by_domain(self, domain: str):
        """Get detailed company enrichment using GraphQL API."""
        # Clean domain
        domain = domain.lower().strip()
        if domain.startswith("http://"):
            domain = domain[7:]
        if domain.startswith("https://"):
            domain = domain[8:]
        if domain.startswith("www."):
            domain = domain[4:]

        # Try different domain variations
        domain_variations = [domain, f"www.{domain}"]

        for domain_variation in domain_variations:
            try:
                # GraphQL mutation for enrichment
                query = """
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
                        }
                    }
                }
                """

                variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

                headers = {"Content-Type": "application/json"}

                response = requests.post(
                    f"{self.base_url}/graphql",
                    params={"apikey": self.api_key},
                    json={"query": query, "variables": variables},
                    headers=headers,
                )

                response.raise_for_status()
                data = response.json()

                if "errors" in data:
                    # Log error response
                    # self._save_api_response(domain, data, is_error=True)  # Commented out for large test runs
                    raise Exception(f"GraphQL errors: {data['errors']}")

                result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                if result.get("companyFound"):
                    company_data = result.get("company")
                    # Log successful response
                    # self._save_api_response(domain, company_data, is_error=False)  # Commented out for large test runs
                    return company_data

            except Exception:
                continue

        # Log when no company found for any variation
        # self._save_api_response(domain, {"message": "No company found for any domain variation"}, is_error=True)  # Commented out for large test runs
        return None
