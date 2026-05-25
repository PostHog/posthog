"""Set WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS instance setting."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django

django.setup()

from posthog.models.instance_setting import get_instance_setting, set_instance_setting

team_ids = [37]
set_instance_setting("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS", team_ids)
print(f"WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS = {get_instance_setting('WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS')!r}")
