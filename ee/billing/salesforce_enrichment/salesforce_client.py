from simple_salesforce import Salesforce
from django.conf import settings


class SalesforceClient:
    """
    Simple Salesforce API client using username/password authentication.
    """

    def __init__(self):
        self.username = settings.SALESFORCE_USERNAME
        self.password = settings.SALESFORCE_PASSWORD
        self.security_token = settings.SALESFORCE_SECURITY_TOKEN

        if not all([self.username, self.password, self.security_token]):
            missing = [
                k
                for k, v in {
                    "SALESFORCE_USERNAME": self.username,
                    "SALESFORCE_PASSWORD": self.password,
                    "SALESFORCE_SECURITY_TOKEN": self.security_token,
                }.items()
                if not v
            ]
            raise ValueError(f"Missing Salesforce credentials: {', '.join(missing)}")

        self._client = None

    @property
    def client(self):
        """Lazy-loaded Salesforce client."""
        if self._client is None:
            self._client = Salesforce(
                username=self.username, password=self.password, security_token=self.security_token
            )
        return self._client

    def query(self, soql: str):
        """Execute a SOQL query."""
        return self.client.query(soql)

    def get_account(self, account_id: str):
        """Get account by ID."""
        return self.client.Account.get(account_id)

    def update_account(self, account_id: str, data: dict):
        """Update account with given data."""
        return self.client.Account.update(account_id, data)
