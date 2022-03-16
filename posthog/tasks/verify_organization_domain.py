from posthog.celery import app
from posthog.models import OrganizationDomain


@app.task(bind=True, ignore_result=True, max_retries=1)
def verify_domain(self, domain_id: str) -> None:
    """
    Performs a DNS verification for a specific domain.
    """
    instance = OrganizationDomain.objects.get(id=domain_id)
    instance.attempt_verification()
