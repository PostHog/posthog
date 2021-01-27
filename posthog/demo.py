import json
import random
import secrets
from pathlib import Path
from typing import List

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from rest_framework.request import Request

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.ee import is_ee_enabled
from posthog.models import (
    Action,
    ActionStep,
    Dashboard,
    DashboardItem,
    Element,
    Event,
    FeatureFlag,
    Organization,
    Person,
    PersonDistinctId,
    Team,
    User,
)
from posthog.models.utils import UUIDT
from posthog.utils import render_template

ORGANIZATION_NAME = "HogFlix"
TEAM_NAME = "HogFlix Demo App"


def _create_anonymous_users(team: Team, base_url: str) -> None:
    with open(Path("posthog/demo_data.json").resolve(), "r") as demo_data_file:
        demo_data = json.load(demo_data_file)

    Person.objects.bulk_create([Person(team=team, properties={"is_demo": True}) for _ in range(0, 100)])
    distinct_ids: List[PersonDistinctId] = []
    events: List[Event] = []
    days_ago = 7
    demo_data_index = 0
    for index, person in enumerate(Person.objects.filter(team=team)):
        if index > 0 and index % 14 == 0:
            days_ago -= 1

        distinct_id = str(UUIDT())
        distinct_ids.append(PersonDistinctId(team=team, person=person, distinct_id=distinct_id))

        # Add first user more 3 distinct id's
        if index == 0:
            for _ in range(0, 3):
                distinct_ids.append(PersonDistinctId(team=team, person=person, distinct_id=str(UUIDT())))

        date = now() - relativedelta(days=days_ago)
        browser = random.choice(["Chrome", "Safari", "Firefox"])
        events.append(
            Event(
                team=team,
                event="$pageview",
                distinct_id=distinct_id,
                properties={"$current_url": base_url, "$browser": browser, "$lib": "web"},
                timestamp=date,
            )
        )
        if index % 3 == 0:
            person.properties.update(demo_data[demo_data_index])
            person.is_identified = True
            person.save()
            demo_data_index += 1
            Event.objects.create(
                team=team,
                distinct_id=distinct_id,
                event="$autocapture",
                properties={"$current_url": base_url, "$browser": browser, "$lib": "web", "$event_type": "click",},
                timestamp=date + relativedelta(seconds=14),
                elements=[
                    Element(
                        tag_name="a",
                        href="/demo/1",
                        attr_class=["btn", "btn-success"],
                        attr_id="sign-up",
                        text="Sign up",
                    ),
                    Element(tag_name="form", attr_class=["form"]),
                    Element(tag_name="div", attr_class=["container"]),
                    Element(tag_name="body"),
                    Element(tag_name="html"),
                ],
            )
            events.append(
                Event(
                    event="$pageview",
                    team=team,
                    distinct_id=distinct_id,
                    properties={"$current_url": "%s/1" % base_url, "$browser": browser, "$lib": "web",},
                    timestamp=date + relativedelta(seconds=15),
                )
            )
            if index % 4 == 0:
                Event.objects.create(
                    team=team,
                    event="$autocapture",
                    distinct_id=distinct_id,
                    properties={
                        "$current_url": "%s/1" % base_url,
                        "$browser": browser,
                        "$lib": "web",
                        "$event_type": "click",
                    },
                    timestamp=date + relativedelta(seconds=29),
                    elements=[
                        Element(tag_name="button", attr_class=["btn", "btn-success"], text="Sign up!",),
                        Element(tag_name="form", attr_class=["form"]),
                        Element(tag_name="div", attr_class=["container"]),
                        Element(tag_name="body"),
                        Element(tag_name="html"),
                    ],
                )
                events.append(
                    Event(
                        event="$pageview",
                        team=team,
                        distinct_id=distinct_id,
                        properties={"$current_url": "%s/2" % base_url, "$browser": browser, "$lib": "web",},
                        timestamp=date + relativedelta(seconds=30),
                    )
                )
                if index % 5 == 0:
                    Event.objects.create(
                        team=team,
                        event="$autocapture",
                        distinct_id=distinct_id,
                        properties={
                            "$current_url": "%s/2" % base_url,
                            "$browser": browser,
                            "$lib": "web",
                            "$event_type": "click",
                        },
                        timestamp=date + relativedelta(seconds=59),
                        elements=[
                            Element(tag_name="button", attr_class=["btn", "btn-success"], text="Pay $10",),
                            Element(tag_name="form", attr_class=["form"]),
                            Element(tag_name="div", attr_class=["container"]),
                            Element(tag_name="body"),
                            Element(tag_name="html"),
                        ],
                    )
                    events.append(
                        Event(
                            event="purchase",
                            team=team,
                            distinct_id=distinct_id,
                            properties={"price": 10},
                            timestamp=date + relativedelta(seconds=60),
                        )
                    )
                    events.append(
                        Event(
                            event="$pageview",
                            team=team,
                            distinct_id=distinct_id,
                            properties={"$current_url": "%s/3" % base_url, "$browser": browser, "$lib": "web",},
                            timestamp=date + relativedelta(seconds=60),
                        )
                    )
    team.event_properties_numerical.append("purchase")
    team.save()
    PersonDistinctId.objects.bulk_create(distinct_ids)
    Event.objects.bulk_create(events)


def _create_funnel(team: Team, base_url: str) -> None:
    homepage = Action.objects.create(team=team, name="HogFlix homepage view")
    ActionStep.objects.create(action=homepage, event="$pageview", url=base_url, url_matching="exact")

    user_signed_up = Action.objects.create(team=team, name="HogFlix signed up")
    ActionStep.objects.create(
        action=user_signed_up, event="$autocapture", url="%s/1" % base_url, url_matching="contains", selector="button",
    )

    user_paid = Action.objects.create(team=team, name="HogFlix paid")
    ActionStep.objects.create(
        action=user_paid, event="$autocapture", url="%s/2" % base_url, url_matching="contains", selector="button",
    )

    dashboard = Dashboard.objects.create(name="Default", pinned=True, team=team, share_token=secrets.token_urlsafe(22))
    DashboardItem.objects.create(
        team=team,
        dashboard=dashboard,
        name="HogFlix signup -> watching movie",
        filters={
            "actions": [
                {"id": homepage.id, "name": "HogFlix homepage view", "order": 0, "type": TREND_FILTER_TYPE_ACTIONS},
                {"id": user_signed_up.id, "name": "HogFlix signed up", "order": 1, "type": TREND_FILTER_TYPE_ACTIONS,},
                {"id": user_paid.id, "name": "HogFlix paid", "order": 2, "type": TREND_FILTER_TYPE_ACTIONS},
            ],
            "insight": "FUNNELS",
        },
    )


def _recalculate(team: Team) -> None:
    actions = Action.objects.filter(team=team)
    for action in actions:
        action.calculate_events()


def demo(request: Request):
    user = request.user
    organization = user.organization
    try:
        team = organization.teams.get(is_demo=True)
    except Team.DoesNotExist:
        team = create_demo_team(organization, user, request)
    user.current_team = team
    user.save()
    if "$pageview" not in team.event_names:
        team.event_names.append("$pageview")
        team.event_names_with_usage.append({"event": "$pageview", "usage_count": None, "volume": None})
        team.save()

    if is_ee_enabled():  # :TRICKY: Lazily backfill missing event data.
        from ee.clickhouse.demo import create_anonymous_users_ch
        from ee.clickhouse.models.event import get_events_by_team

        result = get_events_by_team(team_id=team.pk)
        if not result:
            create_anonymous_users_ch(team=team, base_url=request.build_absolute_uri("/demo"))

    return render_template("demo.html", request=request, context={"api_token": team.api_token})


def create_demo_team(organization: Organization, user: User, request: Request) -> Team:
    team = Team.objects.create_with_data(
        organization=organization, name=TEAM_NAME, ingested_event=True, completed_snippet_onboarding=True, is_demo=True,
    )
    _create_anonymous_users(team=team, base_url=request.build_absolute_uri("/demo"))
    _create_funnel(team=team, base_url=request.build_absolute_uri("/demo"))
    FeatureFlag.objects.create(
        team=team, rollout_percentage=100, name="Sign Up CTA", key="sign-up-cta", created_by=user,
    )
    _recalculate(team=team)

    if is_ee_enabled():
        from ee.clickhouse.demo import create_anonymous_users_ch

        create_anonymous_users_ch(team=team, base_url=request.build_absolute_uri("/demo"))

    return team
