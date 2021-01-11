import json
import random
from pathlib import Path
from typing import List
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from ee.clickhouse.models.clickhouse import generate_clickhouse_uuid
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import update_person_is_identified, update_person_properties
from posthog.models.element import Element
from posthog.models.person import Person
from posthog.models.team import Team


def create_anonymous_users_ch(team: Team, base_url: str) -> None:
    with open(Path("posthog/demo_data.json").resolve(), "r") as demo_data_file:
        demo_data = json.load(demo_data_file)

    demo_data_index = 0
    days_ago = 7
    for index in range(0, 100):
        if index > 0 and index % 14 == 0:
            days_ago -= 1

        date = now() - relativedelta(days=days_ago)
        browser = random.choice(["Chrome", "Safari", "Firefox"])

        distinct_id = generate_clickhouse_uuid()
        person = Person.objects.create(team_id=team.pk, distinct_ids=[distinct_id], properties={"is_demo": True})

        event_uuid = uuid4()
        create_event(
            team=team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": base_url, "$browser": browser, "$lib": "web",},
            timestamp=date,
            event_uuid=event_uuid,
        )

        if index % 3 == 0:

            update_person_properties(team_id=team.pk, id=person.uuid, properties=demo_data[demo_data_index])
            update_person_is_identified(team_id=team.pk, id=person.uuid, is_identified=True)
            demo_data_index += 1

            create_event(
                team=team,
                distinct_id=distinct_id,
                event="$autocapture",
                properties={"$current_url": base_url, "$browser": browser, "$lib": "web", "$event_type": "click",},
                timestamp=date + relativedelta(seconds=14),
                event_uuid=event_uuid,
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

            event_uuid = uuid4()
            create_event(
                event="$pageview",
                team=team,
                distinct_id=distinct_id,
                properties={"$current_url": "%s/1" % base_url, "$browser": browser, "$lib": "web",},
                timestamp=date + relativedelta(seconds=15),
                event_uuid=event_uuid,
            )

            if index % 4 == 0:
                create_event(
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
                    event_uuid=event_uuid,
                    elements=[
                        Element(tag_name="button", attr_class=["btn", "btn-success"], text="Sign up!",),
                        Element(tag_name="form", attr_class=["form"]),
                        Element(tag_name="div", attr_class=["container"]),
                        Element(tag_name="body"),
                        Element(tag_name="html"),
                    ],
                )

                event_uuid = uuid4()
                create_event(
                    event="$pageview",
                    team=team,
                    distinct_id=distinct_id,
                    properties={"$current_url": "%s/2" % base_url, "$browser": browser, "$lib": "web",},
                    timestamp=date + relativedelta(seconds=30),
                    event_uuid=event_uuid,
                )

                if index % 5 == 0:
                    create_event(
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
                        event_uuid=event_uuid,
                        elements=[
                            Element(tag_name="button", attr_class=["btn", "btn-success"], text="Pay $10",),
                            Element(tag_name="form", attr_class=["form"]),
                            Element(tag_name="div", attr_class=["container"]),
                            Element(tag_name="body"),
                            Element(tag_name="html"),
                        ],
                    )

                    event_uuid = uuid4()
                    create_event(
                        event="purchase",
                        team=team,
                        distinct_id=distinct_id,
                        properties={"price": 10},
                        timestamp=date + relativedelta(seconds=60),
                        event_uuid=event_uuid,
                    )

                    event_uuid = uuid4()
                    create_event(
                        event="$pageview",
                        team=team,
                        distinct_id=distinct_id,
                        properties={"$current_url": "%s/3" % base_url, "$browser": browser, "$lib": "web",},
                        timestamp=date + relativedelta(seconds=60),
                        event_uuid=event_uuid,
                    )

    team.event_properties_numerical.append("purchase")
    team.save()
