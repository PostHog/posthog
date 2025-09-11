from django.conf import settings

from simple_salesforce import Salesforce


def get_salesforce_client() -> Salesforce:
    """Create and return a Salesforce client with validated credentials."""
    username = settings.SALESFORCE_USERNAME
    password = settings.SALESFORCE_PASSWORD
    security_token = settings.SALESFORCE_SECURITY_TOKEN

    missing = []
    if not username:
        missing.append("SALESFORCE_USERNAME")
    if not password:
        missing.append("SALESFORCE_PASSWORD")
    if not security_token:
        missing.append("SALESFORCE_SECURITY_TOKEN")

    if missing:
        raise ValueError(f"Missing Salesforce credentials: {', '.join(missing)}")

    return Salesforce(username=username, password=password, security_token=security_token)
