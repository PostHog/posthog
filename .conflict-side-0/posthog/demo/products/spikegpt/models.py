import datetime as dt
from enum import auto
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import pytz

from posthog.demo.matrix.models import EVENT_PAGELEAVE, SimPerson, SimSessionIntent
from posthog.demo.products.spikegpt.data import FAKE_CHATS

from .taxonomy import URL_HOME

if TYPE_CHECKING:
    from .matrix import SpikeGPTCluster


class SpikeGPTSessionIntent(SimSessionIntent):
    """What the user has in mind for the current session."""

    CONSIDER_PRODUCT = auto()
    CHAT = auto()


class SpikeGPTPerson(SimPerson):
    cluster: "SpikeGPTCluster"

    # Constant properties
    name: str
    email: str
    affinity: float  # 0 roughly means they won't like SpikeGPT, 1 means they will - affects need/satisfaction deltas

    # Internal state - plain
    active_session_intent: Optional[SpikeGPTSessionIntent]

    # Internal state - bounded
    _need: float  # 0 means no need, 1 means desperate
    _satisfaction: float  # -1 means hate, 0 means ambivalence, 1 means love
    _churned: bool

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = self.cluster.person_provider.full_name()
        self.email = self.cluster.person_provider.email()
        self.affinity = (
            self.cluster.random.betavariate(1.8, 1.2) if self.active_client.browser != "Internet Explorer" else 0
        )
        self.has_signed_up = False
        min_need = (0.6 if self.kernel else 0) + self.affinity / 8
        max_need = (0.9 if self.kernel else 0.1) + self.affinity / 10
        self._need = self.cluster.random.uniform(min_need, max_need)
        self._satisfaction = 0.0
        self._churned = False
        while True:
            self.country_code = (
                "US" if self.cluster.random.random() < 0.7132 else self.cluster.address_provider.country_code()
            )
            # mimesis doesn't support choosing cities in a specific country, so these will be pretty odd until they fix this
            self.region = (
                "California"
                if self.country_code == "US" and self.cluster.random.random() < 0.5
                else self.cluster.address_provider.region()
            )
            self.city = (
                "San Francisco"
                if self.region == "California" and self.cluster.random.random() < 0.3
                else self.cluster.address_provider.city()
            )
            self.language = "en-GB" if self.country_code == "GB" else "en-US"

            try:  # Some tiny regions aren't in pytz - we want to omit those
                self.timezone = self.cluster.random.choice(pytz.country_timezones[self.country_code])
            except KeyError:
                continue
            else:
                break

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    # Internal state - bounded

    @property
    def need(self) -> float:
        return self._need

    @need.setter
    def need(self, value):
        self._need = max(0, min(1, value))

    @property
    def satisfaction(self) -> float:
        return self._satisfaction

    @satisfaction.setter
    def satisfaction(self, value):
        self._satisfaction = max(-1, min(1, value))

    # Abstract methods

    def decide_feature_flags(self) -> dict[str, Any]:
        return {}

    def determine_next_session_datetime(self) -> dt.datetime:
        next_session_datetime = self.cluster.simulation_time
        while True:
            next_session_datetime += dt.timedelta(
                seconds=self.cluster.random.betavariate(2.5, 1 + self.need) * (12_000 if self.has_signed_up else 36_800)
                + 24
            )
            time_appropriateness: float
            # Check if it's night
            if 5 < next_session_datetime.hour < 23:
                time_appropriateness = 0.1
            # Check if it's 9 to 5 on a work day
            elif next_session_datetime.weekday() <= 5 and 9 <= next_session_datetime.hour <= 17:
                time_appropriateness = 1
            else:
                time_appropriateness = 0.6

            if self.cluster.random.random() < time_appropriateness:
                return next_session_datetime  # If the time is right, let's act - otherwise, let's advance further

    def determine_session_intent(self) -> Optional[SpikeGPTSessionIntent]:
        if not self.all_time_pageview_counts:
            return SpikeGPTSessionIntent.CONSIDER_PRODUCT
        return SpikeGPTSessionIntent.CHAT

    def simulate_session(self):
        entered_url_directly = self.cluster.random.random() < 0.18
        self.active_client.register({"$referrer": "$direct" if entered_url_directly else "https://www.google.com/"})
        self.go_to_home(None if entered_url_directly else {"utm_source": "google"})

    # Path directions

    def go_to_home(self, query_params=None):
        self.active_client.capture_pageview(add_params_to_url(URL_HOME, query_params))
        self.advance_timer(1.8 + self.cluster.random.betavariate(1.5, 3) * 300)  # Viewing the page
        self.satisfaction += (self.cluster.random.betavariate(1.6, 1.2) - 0.5) * 0.1  # It's a somewhat nice page

        if self.active_session_intent == SpikeGPTSessionIntent.CONSIDER_PRODUCT:
            chance_chat_tried = min(max(0.2 + self.affinity, 0), 1)
            if self.cluster.random.random() < chance_chat_tried:
                self.start_chat()
            else:
                self.active_client.capture(EVENT_PAGELEAVE)
                self._churned = True
        elif self.active_session_intent == SpikeGPTSessionIntent.CHAT:
            self.start_chat()
            self.satisfaction += (self.cluster.random.random() - 0.5) * 0.1
            for _ in range(3):
                if self.satisfaction > 0 and self.cluster.random.random() < 0.3:
                    self.start_chat()

    # Individual actions

    def start_chat(self):
        random_chat = self.cluster.random.choice(FAKE_CHATS)
        conversation_so_far: list[dict] = []
        for message in random_chat:
            # Human messages must naturally take longer to type, while AI ones are quick
            if message["role"] == "human":
                self.advance_timer(2 + len(message["content"]) / 10)
                self.active_client.capture("sent chat message", {"content": message["content"]})
            else:
                with self.cluster.matrix.server_client.trace_ai(
                    distinct_id=self.active_client.active_distinct_id, input_state={"messages": conversation_so_far}
                ) as (trace_id, set_trace_output):
                    # Chat generation
                    generation_time = len(message["content"]) / 25
                    self.advance_timer(1 + generation_time)
                    self.cluster.matrix.server_client.capture_ai_generation(
                        distinct_id=self.active_client.active_distinct_id,
                        input=conversation_so_far,
                        output_content=message["content"],
                        latency=generation_time,
                        trace_id=trace_id,
                    )
                    # Memorizer, which determines what memories to save using tool calling
                    generation_time = len(message["content"]) / 37
                    self.advance_timer(1 + generation_time)
                    self.cluster.matrix.server_client.capture_ai_generation(
                        distinct_id=self.active_client.active_distinct_id,
                        input=[
                            {
                                "role": "system",
                                "content": """
Your task is to determine if there's something worth remembering about the user from the following conversation.
Use the "update_memory" tool for each piece of information worth adding to your memory. The user said:""".strip(),
                            },
                            {
                                "role": "human",
                                "content": f'''
My message is:\n{message["content"]}\n\nWhat should you remember from this?
Output only the concise information to memorize, prefixed with "REMEMBER: "'''.strip(),
                            },
                        ],
                        output_content="REMEMBER: Blah blah blah.",
                        latency=generation_time,
                        model="gpt-4o-mini",
                        trace_id=trace_id,
                    )
                    set_trace_output({"messages": [*conversation_so_far, message], "memories": ["Blah blah blah."]})
            conversation_so_far = [*conversation_so_far, message]  # Copying here so that every event's list is distinct


def add_params_to_url(url, query_params):
    if not query_params:
        return url
    parsed_url = urlparse(url)
    encoded_query = urlencode(query_params)
    new_query = f"{parsed_url.query}&{encoded_query}" if parsed_url.query else encoded_query
    return urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment)
    )
