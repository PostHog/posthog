from django.conf import settings

from posthog.urls import opt_slash_path
from posthog.views import robots_txt

urlpatterns = []

# Allow crawling on PostHog Cloud, disable by default for all self-hosted installations
if not settings.MULTI_TENANCY and not settings.ALLOW_SEARCH_ENGINE_CRAWLING:
    urlpatterns.append(opt_slash_path("robots.txt", robots_txt))
