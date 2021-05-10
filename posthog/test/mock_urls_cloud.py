from posthog.urls import opt_slash_path
from posthog.views import robots_txt

settings = {"MULTI_TENANCY": True}

urlpatterns = []

if not settings["MULTI_TENANCY"]:
    urlpatterns.append(opt_slash_path("robots.txt", robots_txt))
