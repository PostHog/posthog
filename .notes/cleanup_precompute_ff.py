"""Delete the local web-analytics-precompute FF (no longer used)."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django

django.setup()

from posthog.models import FeatureFlag

deleted, _ = FeatureFlag.objects.filter(key="web-analytics-precompute").delete()
print(f"deleted {deleted} feature flag rows")
