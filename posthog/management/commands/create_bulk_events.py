import random
import json
import uuid
import psycopg2
from urllib.parse import urlparse
from django.conf import settings

from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django.core import serializers

from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import List
import time
from typing import Iterator, Optional
import io

from posthog.models import (
    Event,
    Element,
    Team,
    Person,
    PersonDistinctId,
    Funnel,
    Action,
    ActionStep,
    FunnelStep,
)


def clean_csv_value(value: Optional[any]) -> str:
    if value is None:
        return r"\N"
    return str(value).replace("\n", "\\n")


class StringIteratorIO(io.TextIOBase):
    def __init__(self, iter: Iterator[str]):
        self._iter = iter
        self._buff = ""

    def readable(self) -> bool:
        return True

    def _read1(self, n: Optional[int] = None) -> str:
        while not self._buff:
            try:
                self._buff = next(self._iter)
            except StopIteration:
                break
        ret = self._buff[:n]
        self._buff = self._buff[len(ret) :]
        return ret

    def read(self, n: Optional[int] = None) -> str:
        line = []
        if n is None or n < 0:
            while True:
                m = self._read1()
                if not m:
                    break
                line.append(m)
        else:
            while n > 0:
                m = self._read1(n)
                if not m:
                    break
                n -= len(m)
                line.append(m)
        return "".join(line)


class Command(BaseCommand):
    help = "Create bulk events for testing"

    def add_arguments(self, parser):
        parser.add_argument("--team_id", nargs="+", type=int, help="specify the team id eg. --team_id 1")
        parser.add_argument(
            "--mode",
            nargs="+",
            default=["create"],
            help="""
        'delete' for deleting bulk demo data 
        or 'create' for creating bulk demo data;
        default 'create'
        eg. --mode delete
        """,
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        mode = options["mode"][0]

        if not team_id:
            print("Please specify the --team id")
            return

        team = Team.objects.get(pk=team_id[0])

        with open(Path("posthog/demo_data.json").resolve(), "r") as demo_data_file:
            demo_data = json.load(demo_data_file)

        base_url = "127.0.0.1/bulk_demo/"

        if mode.lower() == "delete":
            start_time = time.time()
            self._delete_demo_data(team)
            print("--- %s seconds ---" % (time.time() - start_time))
        else:
            self._delete_demo_data(team)
            self._create_funnel(base_url, team)
            start_time = time.time()
            self._create_events(demo_data, team, base_url)
            print("--- %s seconds ---" % (time.time() - start_time))

    def _create_events(self, demo_data, team, base_url):
        result = urlparse(settings.DATABASE_URL)

        database = result.path[1:]
        hostname = result.hostname
        try:
            conn = psycopg2.connect(dbname=database, host=hostname)
        except:
            print("Unable to connect to the database")

        conn.autocommit = True
        cur = conn.cursor()

        Person.objects.bulk_create([Person(team=team, properties={"is_demo": True}) for _ in range(0, 100)])

        distinct_ids: List[PersonDistinctId] = []
        demo_data_index = 0

        for index, person in enumerate(Person.objects.filter(team=team)):
            distinct_id = str(uuid.uuid4())
            distinct_ids.append(PersonDistinctId(team=team, person=person, distinct_id=distinct_id))

            if index % 3 == 0:
                person.properties.update(demo_data[demo_data_index])
                person.save()
                demo_data_index += 1

            events_string_iterator = StringIteratorIO(
                (
                    "|".join(
                        map(
                            clean_csv_value,
                            (
                                random.choice(["autocapture", "$pageview", "$hello"]),
                                json.dumps(
                                    {
                                        "$current_url": base_url + random.choice(["", "1/", "2/"]),
                                        "$browser": random.choice(["Chrome", "Safari", "Firefox"]),
                                        "$lib": "web",
                                    }
                                ),
                                json.dumps(
                                    {
                                        "tag_name": random.choice(["a", "href"]),
                                        "attr_class": ["btn", "btn-success"],
                                        "attr_id": random.choice(["sign-up", "click"]),
                                        "text": random.choice(["Sign up", "Pay $10"]),
                                    }
                                ),
                                now() - relativedelta(days=random.choice(range(7))) + relativedelta(seconds=15),
                                team.id,
                                distinct_id,
                            ),
                        )
                    )
                    + "\n"
                    for _ in range(10000)
                )
            )

            cur.copy_from(
                events_string_iterator,
                "posthog_event",
                sep="|",
                columns=["event", "properties", "elements", "timestamp", "team_id", "distinct_id",],
            )

        PersonDistinctId.objects.bulk_create(distinct_ids)
        cur.close()

    def _delete_demo_data(self, team):
        result = urlparse(settings.DATABASE_URL)

        database = result.path[1:]
        hostname = result.hostname
        try:
            conn = psycopg2.connect(dbname=database, host=hostname)
        except:
            print("Unable to connect to the database")

        conn.autocommit = True
        cur = conn.cursor()

        people = PersonDistinctId.objects.filter(team=team, person__properties__is_demo=True)
        distinct_ids = tuple([item["distinct_id"] for item in list(people.values("distinct_id"))])

        if distinct_ids:
            query = "DELETE from posthog_event WHERE distinct_id in {}".format(str(distinct_ids))
            cur.execute(query)
            cur.close()
        Person.objects.filter(team=team, properties__is_demo=True).delete()
        Funnel.objects.filter(team=team, name__contains="HogFlix").delete()
        Action.objects.filter(team=team, name__contains="HogFlix").delete()

    def _create_funnel(self, base_url, team):
        homepage = Action.objects.create(team=team, name="HogFlix homepage view")
        ActionStep.objects.create(action=homepage, event="$pageview", url=base_url, url_matching="exact")

        user_signed_up = Action.objects.create(team=team, name="HogFlix signed up")
        ActionStep.objects.create(
            action=homepage, event="$autocapture", url="%s1/" % base_url, url_matching="exact",
        )

        user_paid = Action.objects.create(team=team, name="HogFlix paid")
        ActionStep.objects.create(
            action=homepage, event="$autocapture", url="%s2/" % base_url, url_matching="exact",
        )

        funnel = Funnel.objects.create(team=team, name="HogFlix signup -> watching movie")
        FunnelStep.objects.create(funnel=funnel, action=homepage, order=0)
        FunnelStep.objects.create(funnel=funnel, action=user_signed_up, order=1)
        FunnelStep.objects.create(funnel=funnel, action=user_paid, order=2)
