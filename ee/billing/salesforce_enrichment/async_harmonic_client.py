import asyncio
import aiohttp
import json
import os
from datetime import datetime
from typing import Optional, Any
from django.conf import settings


class AsyncHarmonicClient:
    """
    Async Harmonic API client for concurrent company enrichment.

    Based on PostHog's async patterns (AI Vector Sync, S3 Batch Export).
    Uses asyncio.Semaphore for concurrency control and aiohttp for async requests.
    """

    def __init__(self, max_concurrent_requests: int = 5):
        self.api_key = settings.HARMONIC_API_KEY
        if not self.api_key:
            raise ValueError("Missing Harmonic API key: HARMONIC_API_KEY")

        self.base_url = settings.HARMONIC_BASE_URL
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.session: Optional[aiohttp.ClientSession] = None

        # Setup logging directory (same as sync client)
        self.log_dir = os.path.join(os.path.dirname(__file__), "harmonic_api_logs")
        os.makedirs(self.log_dir, exist_ok=True)

    async def _save_api_response(self, domain: str, response_data: dict, is_error: bool = False):
        """Save API response to a local file for debugging and analysis (async version)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_domain = domain.replace(".", "_").replace("/", "_")
        status = "error" if is_error else "success"

        filename = f"{timestamp}_{safe_domain}_{status}_async.json"
        filepath = os.path.join(self.log_dir, filename)

        log_data = {
            "timestamp": datetime.now().isoformat(),
            "domain": domain,
            "status": status,
            "response": response_data,
        }

        # Use asyncio to write file without blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: json.dump(log_data, open(filepath, "w"), indent=2, default=str))

        return filepath

    async def __aenter__(self):
        """Async context manager entry - create session."""
        timeout = aiohttp.ClientTimeout(total=30)  # 30s timeout per request
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close session."""
        if self.session:
            await self.session.close()

    def _clean_domain(self, domain: str) -> str:
        """Clean domain name (same logic as sync client)."""
        domain = domain.lower().strip()
        if domain.startswith("http://"):
            domain = domain[7:]
        if domain.startswith("https://"):
            domain = domain[8:]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    async def enrich_company_by_domain(self, domain: str) -> Optional[dict[str, Any]]:
        """
        Async version of company enrichment with semaphore-controlled concurrency.

        Uses PostHog's pattern: semaphore for rate limiting + session reuse.
        """
        async with self.semaphore:  # Limit concurrent requests
            domain = self._clean_domain(domain)

            # Try domain variations (same as sync client)
            domain_variations = [domain, f"www.{domain}"]

            for domain_variation in domain_variations:
                try:
                    # Same GraphQL query as sync client
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

                    async with self.session.post(
                        f"{self.base_url}/graphql",
                        params={"apikey": self.api_key},
                        json={"query": query, "variables": variables},
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        response.raise_for_status()
                        data = await response.json()

                        if "errors" in data:
                            # Log error response
                            # await self._save_api_response(domain, data, is_error=True)  # Commented out for large test runs
                            continue  # Try next domain variation

                        result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                        if result.get("companyFound"):
                            company_data = result.get("company")
                            # Log successful response
                            # await self._save_api_response(domain, company_data, is_error=False)  # Commented out for large test runs
                            return company_data

                except Exception:
                    continue  # Try next domain variation

            # Log when no company found for any variation
            # await self._save_api_response(domain, {"message": "No company found for any domain variation"}, is_error=True)  # Commented out for large test runs
            return None

    async def enrich_companies_batch(self, domains: list[str]) -> list[Optional[dict[str, Any]]]:
        """
        Batch enrichment using asyncio.gather - PostHog's standard pattern.

        Processes multiple domains concurrently with return_exceptions=True
        to prevent individual failures from stopping the batch.
        """
        if not domains:
            return []

        # Create tasks for concurrent execution
        tasks = [self.enrich_company_by_domain(domain) for domain in domains]

        # Use asyncio.gather with return_exceptions=True (PostHog pattern)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions
        processed_results = []
        for _i, result in enumerate(results):
            if isinstance(result, Exception):
                # Log exception but don't fail the batch
                processed_results.append(None)
            else:
                processed_results.append(result)

        return processed_results
