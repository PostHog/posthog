from typing import Any
import requests
from urllib.parse import urlparse
import structlog
from django.utils import timezone
from rest_framework import response, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.viewsets import ViewSet
from datetime import timedelta
from posthog.cache_utils import cache_for

from posthog.models import Organization

from posthog.models.organization import OrganizationMembership
from posthog.cloud_utils import get_cached_instance_license
from ee.billing.billing_manager import BillingManager


logger = structlog.get_logger(__name__)

STARTUP_ZAPIER_WEBHOOK_URL = "https://hooks.zapier.com/hooks/catch/8898847/20d1fd1/"
YC_ZAPIER_WEBHOOK_URL = "https://hooks.zapier.com/hooks/catch/8898847/20dlxpo/"

# Match the same list used in frontend/src/scenes/startups/startupProgramLogic.ts
PUBLIC_EMAIL_DOMAINS = [
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "protonmail.com",
    "icloud.com",
    "mail.com",
    "zoho.com",
    "yandex.com",
    "gmx.com",
    "live.com",
    "mail.ru",
]


def extract_domain_from_url(url: str) -> str:
    """Extract domain from URL, removing 'www.' prefix."""
    try:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        return domain.replace("www.", "")
    except Exception:
        return url.replace("www.", "")


def extract_domain_from_email(email: str) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.split("@")[1].lower()
    if domain in PUBLIC_EMAIL_DOMAINS:
        return None
    return domain


def verify_yc_batch_membership(yc_batch: str, organization_name: str, user_email: str) -> bool:
    """
    Verify if a company is part of the specified YC batch by checking against the YC API.

    Args:
        yc_batch: The YC batch code (e.g., 'W22', 'S23')
        organization_name: The name of the organization to check
        user_email: User email to check domain match

    Returns:
        bool: True if the company is verified in the batch, False otherwise
    """
    if not yc_batch or yc_batch == "Earlier":
        return False

    try:
        url = f"https://yc-oss.github.io/api/batches/{yc_batch.lower()}.json"
        response = requests.get(url, timeout=5)  # 5 second timeout

        if not response.ok:
            return False

        companies = response.json()

        normalized_org_name = organization_name.lower().strip()

        email_domain = extract_domain_from_email(user_email)

        # Check if the company is in the batch
        for company in companies:
            if not company.get("name") and not company.get("website"):
                continue

            company_name = company.get("name", "").lower().strip()

            company_domain = None
            if company.get("website"):
                company_domain = extract_domain_from_url(company.get("website", ""))

            name_match = company_name == normalized_org_name
            domain_match = email_domain and company_domain and email_domain == company_domain

            if name_match or domain_match:
                return True

        return False
    except Exception:
        # If any error occurs, default to requiring manual verification
        return False


def check_organization_eligibility(organization_id: str, user: Any) -> str:
    """
    Validates that an organization is eligible for the startup program.

    Returns organization_id if valid, otherwise raises ValidationError.
    """
    try:
        organization = Organization.objects.get(id=organization_id)

        membership = organization.memberships.filter(user=user).first()
        if not membership or not membership.level >= OrganizationMembership.Level.ADMIN:
            raise ValidationError("You must be an organization admin or owner to apply")

        license = get_cached_instance_license()
        if not license:
            raise ValidationError("No license found")

        billing_manager = BillingManager(license, user)
        billing_info = billing_manager.get_billing(organization)

        if not billing_info.get("has_active_subscription"):
            raise ValidationError("You need an active subscription to apply for the startup program")

        if billing_info.get("startup_program_label"):
            raise ValidationError("Your organization is already in the startup program")

    except Organization.DoesNotExist:
        raise ValidationError("Organization not found")

    return organization_id


class StartupApplicationSerializer(serializers.Serializer):
    program = serializers.ChoiceField(
        required=True,
        choices=["startup", "YC"],
    )
    organization_id = serializers.CharField(required=True)

    # Startup program fields
    raised = serializers.CharField(required=False)
    incorporation_date = serializers.DateField(required=False)

    # YC program fields
    yc_batch = serializers.CharField(required=False)
    yc_proof_screenshot_url = serializers.URLField(required=False)
    yc_merch_count = serializers.IntegerField(required=False, min_value=0, max_value=5)

    def validate_organization_id(self, value: str) -> str:
        return check_organization_eligibility(value, self.context["request"].user)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        program = data["program"]
        errors: dict[str, str] = {}

        if program == "startup":
            if not data.get("raised"):
                errors["raised"] = "Funding amount is required for startup program applications"
            elif not isinstance(data["raised"], str):
                errors["raised"] = "Funding amount must be a string"
            else:
                try:
                    amount = int(data["raised"])
                    if amount >= 5_000_000:
                        errors["raised"] = (
                            "Companies that have raised $5M or more are not eligible for the startup program"
                        )
                except ValueError:
                    errors["raised"] = "Invalid funding amount"

            if not data.get("incorporation_date"):
                errors["incorporation_date"] = "Incorporation date is required for startup program applications"
            elif (timezone.now().date() - data["incorporation_date"]).days > 730:  # 2 years
                errors["incorporation_date"] = "Companies older than 2 years are not eligible for the startup program"

            # Remove YC fields for startups program
            data.pop("yc_batch", None)
            data.pop("yc_proof_screenshot_url", None)
            data.pop("yc_merch_count", None)

        elif program == "YC":
            verified = False

            if not data.get("yc_batch"):
                errors["yc_batch"] = "YC batch is required for YC applications"
            else:
                organization = Organization.objects.get(id=data["organization_id"])
                user = self.context["request"].user
                verified = verify_yc_batch_membership(
                    yc_batch=data["yc_batch"], organization_name=organization.name, user_email=user.email
                )

                if not verified and not data.get("yc_proof_screenshot_url"):
                    errors["yc_proof_screenshot_url"] = (
                        "Screenshot proof is required for YC applications that cannot be automatically verified"
                    )

            data["yc_verified_automatically"] = str(verified)
            data["yc_deal_type"] = get_yc_deal_type(data["yc_batch"])

            # Remove startup fields for YC program
            data.pop("raised", None)
            data.pop("incorporation_date", None)

        else:
            errors["program"] = f"Invalid program type: {program}"

        if errors:
            raise ValidationError(errors)

        return data

    def create(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        user = self.context["request"].user
        organization = Organization.objects.get(id=validated_data["organization_id"])

        zapier_table_data = {
            "submitted_via": "app.posthog.com",
            "submitted_at": timezone.now().isoformat(),
            "email": user.email,
            "domain": extract_domain_from_email(user.email),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "organization_name": organization.name,
            "organization_id": organization.id,
            "customer_id": organization.customer_id,
            "referrer": None,  # not used currently - eventually we'll have custom links for partners and populate it based on that
            **validated_data,
        }

        if zapier_table_data.get("incorporation_date"):
            zapier_table_data["incorporation_date"] = zapier_table_data["incorporation_date"].isoformat()

        # Create a record in Zapier table via webhook
        webhook_url = YC_ZAPIER_WEBHOOK_URL if validated_data.get("program") == "YC" else STARTUP_ZAPIER_WEBHOOK_URL
        requests.post(webhook_url, json=zapier_table_data, timeout=10).raise_for_status()

        # Add a Salesforce contact via webhook
        # Type: 'contact'
        # Source: program
        # Company: organization_name
        # First Name: first_name
        # Last Name: last_name
        # Email: email
        # Startup Domain: domain

        # Non-YC only
        # Incorpation Date: incorporation_date (to be formatted as YYYY-MM-DD) - field name mispelled in Zapier
        # Raised: raised
        # Referrer: referrer

        # YC only
        # YC Batch: yc_batch

        # Excluded for now but can be sent: organization_id, customer_id (Stripe), submitted_at,

        return zapier_table_data


class StartupsViewSet(ViewSet):
    """Handles startup-related functionality."""

    @action(detail=False, methods=["POST"])
    def apply(self, request, *args, **kwargs):
        """Submit startup program application."""
        if not request.user.is_authenticated:
            raise ValidationError("You must be logged in to apply for the startup program")

        serializer = StartupApplicationSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            result = serializer.save()
            return response.Response(result, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.exception("Failed to submit startup application", exc_info=e)
            raise ValidationError("Failed to submit application")


def batch_sort_key(batch_name: str) -> tuple[int, int]:
    """Return a tuple of (year, season_order) for sorting YC batches.
    Season order (descending): F (fall) > S (summer) > X (spring) > W (winter)
    """
    try:
        season = batch_name[0].upper()
        year = int(batch_name[1:])

        # Season order (higher value = earlier in sort)
        season_order = {
            "F": 4,  # Fall
            "S": 3,  # Summer
            "X": 2,  # Sprint
            "W": 1,  # Winter
        }

        if season not in season_order:
            return (-1, -1)

        # Use year as primary sort key, season as secondary
        return (year, season_order[season])
    except (IndexError, ValueError):
        return (-1, -1)


@cache_for(timedelta(hours=24))
def get_sorted_yc_batches() -> list[str]:
    """
    Fetches and sorts YC batches from newest to oldest.
    Returns a list of batch names (e.g. ['X25', 'W25', 'F24', 'S24', 'W24', ...])
    """
    try:
        response = requests.get("https://yc-oss.github.io/api/meta.json", timeout=5)
        response.raise_for_status()
        data = response.json()
        batches = [batch["name"].upper() for batch in data.get("batches", {}).values() if batch.get("name")]

        return sorted(batches, key=batch_sort_key, reverse=True)
    except Exception:
        return []


def get_yc_deal_type(batch: str) -> str:
    """Return the deal type for a YC batch.
    - current: Two most recent batches (current and upcoming) - $50K for 12 months,
    - old: Next 4 batches
    - older: Everything else
    """
    sorted_batches = get_sorted_yc_batches()

    if not sorted_batches or batch.upper() not in sorted_batches:
        return "older"

    batch_index = sorted_batches.index(batch.upper())

    if batch_index < 2:  # First two batches
        return "current"
    elif batch_index < 6:  # Next four batches
        return "old"
    return "older"
