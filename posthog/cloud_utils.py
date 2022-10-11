from django.conf import settings
from django.db.utils import ProgrammingError


def is_cloud():
    # TODO: Possibly cache this for a time?
    try:
        from ee.models import License

        # TRICKY - The license table may not exist if a migration is running
        license = License.objects.first_valid()
        return license.plan == "cloud" if license else settings.MULTI_TENANCY

    # TRICKY - The license table may not exist if a migration is running
    except (ImportError, ProgrammingError):
        return False
