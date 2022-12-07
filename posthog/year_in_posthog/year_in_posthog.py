import os

from django.http import HttpResponse
from django.template.loader import get_template
from sentry_sdk import capture_exception

from posthog import settings
from posthog.year_in_posthog.calculate_2022 import calculate_year_in_posthog_2022


def render_2022(request) -> HttpResponse:
    try:
        data = calculate_year_in_posthog_2022(1)
        context = {
            "debug": settings.DEBUG,
            "api_token": os.environ.get("DEBUG_API_TOKEN", "unknown") if settings.DEBUG else "sTMFPsFhdP1Ssg",
            "data": data,
        }

        template = get_template("2022.html")
        html = template.render(context, request=request)
        return HttpResponse(html)
    except Exception as e:
        capture_exception(e)
        return HttpResponse("Error rendering 2022 page", status=500)
