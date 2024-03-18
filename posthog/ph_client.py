from posthog.utils import get_instance_region
from posthog.cloud_utils import is_cloud


def get_ph_client():
    from posthoganalytics import Posthog

    if not is_cloud():
        return

    # send EU data to EU, US data to US
    api_key = None
    host = None
    region = get_instance_region()
    if region == "EU":
        api_key = "phc_dZ4GK1LRjhB97XozMSkEwPXx7OVANaJEwLErkY1phUF"
        host = "https://eu.i.posthog.com"
    elif region == "US":
        api_key = "sTMFPsFhdP1Ssg"
        host = "https://us.i.posthog.com"

    if not api_key:
        return

    ph_client = Posthog(api_key, host=host)

    return ph_client
