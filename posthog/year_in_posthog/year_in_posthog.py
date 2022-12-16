import os
from typing import Dict, List, Union

import structlog
from django.http import HttpResponse
from django.template.loader import get_template
from django.views.decorators.cache import cache_control
from sentry_sdk import capture_exception

from posthog import settings
from posthog.year_in_posthog.calculate_2022 import calculate_year_in_posthog_2022

logger = structlog.get_logger(__name__)

badge_preference = ["astronaut", "deep_diver", "curator", "flag_raiser", "popcorn_muncher", "scientist", "champion"]

human_badge = {
    "astronaut": "Astronaut",
    "deep_diver": "Deep Diver",
    "curator": "Curator",
    "flag_raiser": "Flag Raiser",
    "popcorn_muncher": "Popcorn muncher",
    "scientist": "Scientist",
    "champion": "Champion",
}

highlight_color = {
    "astronaut": "#E2E8FE",
    "deep_diver": "#41CBC4",
    "curator": "#FFF",
    "flag_raiser": "#FF906E",
    "popcorn_muncher": "#C5A1FF",
    "scientist": "#FFD371",
    "champion": "#FE729D",
}

explanation = {
    "astronaut": "When it comes to data, there are no small steps - only giant leaps. And we think you're out of this world.",
    "deep_diver": "You've dived into your data far deeper than the average Joe (no offence, Joe). What's at the bottom of the data lake? You're going to find out.",
    "curator": "Product analytics is an art, as well as a science. And you're an artist. Your dashboards belong in a museum.",
    "flag_raiser": "You've raised so many feature flags we've started to suspect that semaphore is your first language. Keep it up!",
    "popcorn_muncher": "You're addicted to reality TV. And, by reality TV, we mean session recordings. You care about the UX and we want to celebrate that!",
    "scientist": "You’ve earned this badge from your never ending curiosity and need for knowledge. One result we know for sure, you are doing amazing things. ",
    "champion": "You're unmatched. Unstoppable. You're like the Usain Bolt of hedgehogs! We're grateful to have you as a PostHog power user.",
}


def stats_for_badge(data: Dict, badge: str) -> List[Dict[str, Union[int, str]]]:
    stats = data["stats"]
    # noinspection PyBroadException
    try:
        if badge == "astronaut" or badge == "deep_diver":
            return (
                [{"count": stats["insight_created_count"], "description": "Insights created"}]
                if stats["insight_created_count"]
                else []
            )
        elif badge == "curator":
            return [{"count": stats["dashboards_created_count"], "description": "Dashboards created"}]
        elif badge == "flag_raiser":
            return [{"count": stats["flag_created_count"], "description": "Feature flags created"}]
        elif badge == "popcorn_muncher":
            return [{"count": stats["viewed_recording_count"], "description": "Session recordings viewed"}]
        elif badge == "scientist":
            return [{"count": stats["experiments_created_count"], "description": "Experiments created"}]
        elif badge == "champion":
            return [
                {"count": stats["insight_created_count"], "description": "Insights created"},
                {"count": stats["viewed_recording_count"], "description": "Session recordings viewed"},
                {"count": stats["flag_created_count"], "description": "Feature flags created"},
            ]
        else:
            raise Exception("A user has to have one badge!")
    except Exception as e:
        logger.error(
            "year_in_posthog_2022_error_getting_stats", exc_info=True, exc=e, data=data or "no data", badge=badge
        )
        return []


def sort_list_based_on_preference(badges: List[str]) -> str:
    """sort a list based on its order in badge_preferences and then choose the last one"""
    badges_by_preference = sorted(badges, key=lambda x: badge_preference.index(x))
    return badges_by_preference[-1]


@cache_control(public=True, max_age=300)  # cache for 5 minutes
def render_2022(request, user_uuid: str) -> HttpResponse:
    data = None

    try:
        data = calculate_year_in_posthog_2022(user_uuid)

        badge = sort_list_based_on_preference(data["badges"] or ["astronaut"])
    except Exception as e:
        # because Harry is trying to hack my URLs
        logger.error("year_in_posthog_2022_error_loading_data", exc_info=True, exc=e, data=data or "no data")
        capture_exception(e)
        badge = "astronaut"
        data = data or {"stats": {}}

    try:
        stats = stats_for_badge(data, badge)

        context = {
            "debug": settings.DEBUG,
            "api_token": os.environ.get("DEBUG_API_TOKEN", "unknown") if settings.DEBUG else "sTMFPsFhdP1Ssg",
            "badge": badge,
            "human_badge": human_badge.get(badge),
            "highlight_color": highlight_color.get(badge),
            "image_png": f"badges/2022_{badge}.png",
            "image_webp": f"badges/2022_{badge}.webp",
            "opengraph_image": f"open-graph/2022_{badge}.png",
            "explanation": explanation.get(badge),
            "stats": stats,
            "page_url": f"{request.scheme}://{request.META['HTTP_HOST']}{request.get_full_path()}",
        }

        template = get_template("2022.html")
        html = template.render(context, request=request)
        return HttpResponse(html)
    except Exception as e:
        capture_exception(e)
        logger.error("year_in_posthog_2022_error_rendering_2022_page", exc_info=True, exc=e, data=data or "no data")
        return HttpResponse("Error rendering 2022 page", status=500)
