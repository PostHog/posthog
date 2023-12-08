from django.http import HttpResponse
from django.template.loader import get_template
from django.views.decorators.cache import cache_control
import os
from typing import Dict, List, Union

import structlog

from sentry_sdk import capture_exception

from posthog import settings
from posthog.year_in_posthog.calculate_2023 import calculate_year_in_posthog_2023

logger = structlog.get_logger(__name__)

badge_preference = [
    "astronaut",
    "deep_diver",
    "curator",
    "flag_raiser",
    "popcorn_muncher",
    "scientist",
    "reporter",
    "champion",
]

human_badge = {
    "astronaut": "Astronaut",
    "deep_diver": "Deep Diver",
    "curator": "Curator",
    "flag_raiser": "Flag Raiser",
    "popcorn_muncher": "Popcorn muncher",
    "scientist": "Scientist",
    "reporter": "Reporter",
    "champion": "Champion",
}

highlight_color = {
    "astronaut": "#E2E8FE",
    "deep_diver": "#41CBC4",
    "curator": "#FFF",
    "flag_raiser": "#FF906E",
    "popcorn_muncher": "#C5A1FF",
    "scientist": "#FFD371",
    "reporter": "#F63C00",
    "champion": "#FE729D",
}

explanation = {
    "astronaut": "When it comes to data, there are no small steps - only giant leaps. And we think you're out of this world.",
    "deep_diver": "You've dived into your data far deeper than the average Joe (no offence, Joe). What's at the bottom of the data lake? You're going to find out.",
    "curator": "Product analytics is an art, as well as a science. And you're an artist. Your dashboards belong in a museum.",
    "flag_raiser": "You've raised so many feature flags we've started to suspect that semaphore is your first language. Keep it up!",
    "popcorn_muncher": "You're addicted to reality TV. And, by reality TV, we mean session recordings. You care about the UX and we want to celebrate that!",
    "scientist": "You’ve earned this badge from your never ending curiosity and need for knowledge. One result we know for sure, you are doing amazing things. ",
    "reporter": "This just in: You love asking questions and have a nose for news. Surveys have made you the gossip columnist of PostHog!",
    "champion": "You're unmatched. Unstoppable. You're like the Usain Bolt of hedgehogs! We're grateful to have you as a PostHog power user.",
}


def stats_for_badge(data: Dict, badge: str) -> List[Dict[str, Union[int, str]]]:
    stats = data["stats"]
    # noinspection PyBroadException
    try:
        if badge == "astronaut" or badge == "deep_diver":
            return (
                [{"count": stats["insight_created_count"], "description": "Insights created"}]
                if stats.get("insight_created_count")
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
        elif badge == "reporter":
            return [{"count": stats["surveys_created_count"], "description": "Surveys created"}]
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
            "year_in_posthog_2023_error_getting_stats", exc_info=True, exc=e, data=data or "no data", badge=badge
        )
        return []


def sort_list_based_on_preference(badges: List[str]) -> str:
    """sort a list based on its order in badge_preferences and then choose the last one"""
    badges_by_preference = sorted(badges, key=lambda x: badge_preference.index(x))
    return badges_by_preference[-1]


@cache_control(public=True, max_age=300)  # cache for 5 minutes
def render_2023(request, user_uuid: str) -> HttpResponse:
    data = None

    try:
        data = calculate_year_in_posthog_2023(user_uuid)

        badge = sort_list_based_on_preference(data.get("badges") or ["astronaut"])

        badge_images = {}
        for b in data.get("badges", {}):
            if b != badge:
                badge_images[b] = {
                    "badge": b,
                    "human_badge": human_badge.get(b),
                    "image_png": f"year_in_hog/badges/2023_{b}.png",
                    "image_webp": f"year_in_hog/badges/2023_{b}.webp",
                    "highlight_color": highlight_color.get(b),
                    "explanation": explanation.get(b),
                }

        stats = stats_for_badge(data, badge)

        context = {
            "debug": settings.DEBUG,
            "api_token": os.environ.get("DEBUG_API_TOKEN", "unknown") if settings.DEBUG else "sTMFPsFhdP1Ssg",
            "badge": badge,
            "badges": badge_images if len(badge_images.items()) > 1 else {},
            "human_badge": human_badge.get(badge),
            "highlight_color": highlight_color.get(badge),
            "image_png": f"year_in_hog/badges/2023_{badge}.png",
            "image_webp": f"year_in_hog/badges/2023_{badge}.webp",
            "opengraph_image": f"year_in_hog/open-graph/2023_{badge}.png",
            "explanation": explanation.get(badge),
            "stats": stats,
            "page_url": f"{request.scheme}://{request.META['HTTP_HOST']}{request.get_full_path()}",
        }

        template = get_template("2023.html")
        html = template.render(context, request=request)
        return HttpResponse(html)
    except Exception as e:
        capture_exception(e)
        logger.error("year_in_posthog_2023_error_rendering_2023_page", exc_info=True, exc=e, data=data or "no data")
        template = get_template("hibernating.html")
        html = template.render({"message": "Something went wrong 🫠"}, request=request)
        return HttpResponse(html, status=500)


@cache_control(public=True, max_age=300)  # cache for 5 minutes
def render_2022(request, user_uuid: str) -> HttpResponse:
    template = get_template("hibernating.html")
    html = template.render({"message": "This is the 2022 Year in PostHog. That's too long ago 🙃"}, request=request)
    return HttpResponse(html)
