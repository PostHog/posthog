import math
import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import pytz

from posthog.demo.matrix.models import EVENT_AUTOCAPTURE, Effect, SimPerson, SimSessionIntent

from .taxonomy import (
    EVENT_DELETED_FILE,
    EVENT_DOWNGRADED_PLAN,
    EVENT_DOWNLOADED_FILE,
    EVENT_INVITED_TEAM_MEMBER,
    EVENT_LOGGED_IN,
    EVENT_LOGGED_OUT,
    EVENT_PAID_BILL,
    EVENT_REMOVED_TEAM_MEMBER,
    EVENT_SHARED_FILE_LINK,
    EVENT_SIGNED_UP,
    EVENT_UPGRADED_PLAN,
    EVENT_UPLOADED_FILE,
    GROUP_TYPE_ACCOUNT,
    NEW_SIGNUP_PAGE_FLAG_KEY,
    NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT,
    SIGNUP_SUCCESS_RATE_CONTROL,
    SIGNUP_SUCCESS_RATE_TEST,
    URL_ACCOUNT_BILLING,
    URL_ACCOUNT_SETTINGS,
    URL_ACCOUNT_TEAM,
    URL_FILES,
    URL_HOME,
    URL_LOGIN,
    URL_MARIUS_TECH_TIPS,
    URL_PRICING,
    URL_PRODUCT_AD_LINK_1,
    URL_PRODUCT_AD_LINK_2,
    URL_SIGNUP,
    dyn_url_file,
    dyn_url_invite,
)

if TYPE_CHECKING:
    from posthog.demo.products.hedgebox.matrix import HedgeboxCluster


class HedgeboxSessionIntent(SimSessionIntent):
    """What the user has in mind for the current session."""

    CONSIDER_PRODUCT = auto()
    CHECK_MARIUS_TECH_TIPS_LINK = auto()
    UPLOAD_FILE_S = auto()
    DELETE_FILE_S = auto()
    DOWNLOAD_OWN_FILE_S = auto()
    SHARE_FILE = auto()
    VIEW_SHARED_FILE = auto()
    INVITE_TEAM_MEMBER = auto()
    REMOVE_TEAM_MEMBER = auto()
    JOIN_TEAM = auto()
    UPGRADE_PLAN = auto()
    DOWNGRADE_PLAN = auto()
    CHECK_LINKED_PR = auto()


class HedgeboxPlan(StrEnum):
    PERSONAL_FREE = "personal/free"
    PERSONAL_PRO = "personal/pro"
    BUSINESS_STANDARD = "business/standard"
    BUSINESS_ENTERPRISE = "business/enterprise"

    @property
    def is_business(self) -> bool:
        return self.startswith("business/")

    @property
    def successor(self) -> Optional["HedgeboxPlan"]:
        if self == HedgeboxPlan.PERSONAL_FREE:
            return HedgeboxPlan.PERSONAL_PRO
        elif self == HedgeboxPlan.BUSINESS_STANDARD:
            return HedgeboxPlan.BUSINESS_ENTERPRISE
        else:
            return None

    @property
    def predecessor(self) -> Optional["HedgeboxPlan"]:
        if self == HedgeboxPlan.PERSONAL_PRO:
            return HedgeboxPlan.PERSONAL_FREE
        elif self == HedgeboxPlan.BUSINESS_ENTERPRISE:
            return HedgeboxPlan.BUSINESS_STANDARD
        else:
            return None


@dataclass
class HedgeboxFile:
    id: str
    type: str
    size_b: int
    popularity: float

    def __hash__(self) -> int:
        return hash(id)


@dataclass
class HedgeboxAccount:
    id: str
    created_at: dt.datetime
    team_members: set["HedgeboxPerson"]
    plan: HedgeboxPlan
    files: set[HedgeboxFile] = field(default_factory=set)
    was_billing_scheduled: bool = field(default=False)

    @property
    def current_allowed_mb(self) -> int:
        if self.plan == HedgeboxPlan.PERSONAL_FREE:
            return 10_000
        elif self.plan == HedgeboxPlan.PERSONAL_PRO:
            return 1_000_000
        elif self.plan == HedgeboxPlan.BUSINESS_STANDARD:
            return 5_000_000
        elif self.plan == HedgeboxPlan.BUSINESS_ENTERPRISE:
            return 100_000_000
        else:
            raise ValueError(f"Unknown plan: {self.plan}")

    @property
    def current_used_mb(self) -> int:
        return sum(file.size_b for file in self.files)

    @property
    def allocation_used_fraction(self) -> float:
        return self.current_used_mb / self.current_allowed_mb

    @property
    def current_monthly_bill_usd(self) -> float:
        if self.plan == HedgeboxPlan.PERSONAL_FREE:
            return 0
        elif self.plan == HedgeboxPlan.PERSONAL_PRO:
            return 10
        elif self.plan == HedgeboxPlan.BUSINESS_STANDARD:
            return 10 * len(self.team_members)
        elif self.plan == HedgeboxPlan.BUSINESS_ENTERPRISE:
            return 20 * len(self.team_members)
        else:
            raise ValueError(f"Unknown plan: {self.plan}")


class HedgeboxPerson(SimPerson):
    cluster: "HedgeboxCluster"

    # Constant properties
    name: str
    email: str
    affinity: float  # 0 roughly means they won't like Hedgebox, 1 means they will - affects need/satisfaction deltas
    falls_into_new_signup_page_bucket: bool
    watches_marius_tech_tips: bool

    # Internal state - plain
    active_session_intent: Optional[HedgeboxSessionIntent]
    invite_to_use_id: Optional[str]
    file_to_view: Optional[HedgeboxFile]
    is_invitable: bool

    # Internal state - bounded
    _need: float  # 0 means no need, 1 means desperate
    _satisfaction: float  # -1 means hate, 0 means ambivalence, 1 means love
    _churned: bool
    _personal_account: Optional[HedgeboxAccount]  # In company clusters the cluster-level account is used

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = self.cluster.person_provider.full_name()
        self.email = self.cluster.person_provider.email()
        self.affinity = (
            self.cluster.random.betavariate(1.8, 1.2)
            if self.active_client.browser != "Internet Explorer"
            else self.cluster.random.betavariate(1, 1.4)
        )
        self.falls_into_new_signup_page_bucket = self.cluster.random.random() < (
            NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT / 100
        )
        self.watches_marius_tech_tips = self.cluster.random.random() < 0.04
        self.invite_to_use_id = None
        self.file_to_view = None
        self.is_invitable = True
        min_need = (0.6 if self.kernel else 0) + self.affinity / 8
        max_need = (0.9 if self.kernel else 0.1) + self.affinity / 10
        self._need = self.cluster.random.uniform(min_need, max_need)
        self._satisfaction = 0.0
        self._churned = False
        self._personal_account = None
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

    @property
    def account(self) -> Optional[HedgeboxAccount]:
        return self.cluster._business_account if self.cluster.company else self._personal_account

    @account.setter
    def account(self, value):
        if self.cluster.company:
            self.cluster._business_account = value
        else:
            self._personal_account = value

    @property
    def has_signed_up(self) -> bool:
        return self.account is not None and self in self.account.team_members

    # Abstract methods

    def decide_feature_flags(self) -> dict[str, Any]:
        if (
            self.cluster.simulation_time >= self.cluster.matrix.new_signup_page_experiment_start
            and self.cluster.simulation_time < self.cluster.matrix.new_signup_page_experiment_end
        ):
            return {NEW_SIGNUP_PAGE_FLAG_KEY: "test" if self.falls_into_new_signup_page_bucket else "control"}
        else:
            return {}

    def determine_next_session_datetime(self) -> dt.datetime:
        next_session_datetime = self.cluster.simulation_time
        while True:
            next_session_datetime += dt.timedelta(
                seconds=self.cluster.random.betavariate(2.5, 1 + self.need)
                * (36_000 if self.has_signed_up else 172_800)
                + 24
            )
            time_appropriateness: float
            # Check if it's night
            if 5 < next_session_datetime.hour < 23:
                time_appropriateness = 0.1
            # Check if it's 9 to 5 on a work day
            elif next_session_datetime.weekday() <= 5 and 9 <= next_session_datetime.hour <= 17:
                # Business users most likely to be active during the work day, personal users just the opposite
                time_appropriateness = 1 if self.cluster.company else 0.3
            else:
                time_appropriateness = 0.2 if self.cluster.company else 1

            if self.cluster.random.random() < time_appropriateness:
                return next_session_datetime  # If the time is right, let's act - otherwise, let's advance further

    def determine_session_intent(self) -> Optional[HedgeboxSessionIntent]:
        weeks_since_account_creation = (
            (self.cluster.simulation_time - self.account.created_at).total_seconds() / 86_400 / 7 if self.account else 0
        )
        boredom_churned = self.cluster.random.random() < math.log2(weeks_since_account_creation + 1) / 4 * (
            0.75 - self.affinity
        )
        satisfaction_churned = self.satisfaction < -0.5 and self.need < 0.9
        if boredom_churned or satisfaction_churned:
            self._churned = True
        if self._churned or self.affinity < 0.1 or not self.kernel and self.cluster.company:
            # Very low affinity users aren't interested
            # Non-kernel business users can't log in or sign up
            return None
        possible_intents_with_weights: list[tuple[HedgeboxSessionIntent, float]] = []
        if self.invite_to_use_id:
            possible_intents_with_weights.append((HedgeboxSessionIntent.JOIN_TEAM, 1))
        elif self.file_to_view:
            possible_intents_with_weights.append((HedgeboxSessionIntent.VIEW_SHARED_FILE, 1))
        elif not self.has_signed_up:
            if self.all_time_pageview_counts[URL_HOME] < 2:
                possible_intents_with_weights.append((HedgeboxSessionIntent.CONSIDER_PRODUCT, 2))
            if self.watches_marius_tech_tips and not self.all_time_pageview_counts[URL_MARIUS_TECH_TIPS]:
                possible_intents_with_weights.append((HedgeboxSessionIntent.CHECK_MARIUS_TECH_TIPS_LINK, 1))
        else:
            assert self.account is not None
            file_count = len(self.account.files)
            # The more files, the more likely to delete/download/share rather than upload
            possible_intents_with_weights.extend(
                [
                    (
                        HedgeboxSessionIntent.DELETE_FILE_S,
                        math.log10(file_count) / 8 if file_count else 0,
                    ),
                    (
                        HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S,
                        math.log10(file_count + 1) if file_count else 0,
                    ),
                    (
                        HedgeboxSessionIntent.SHARE_FILE,
                        math.log10(file_count) / 3 if file_count else 0,
                    ),
                ]
            )
            if self.account.allocation_used_fraction < 0.99:
                possible_intents_with_weights.append((HedgeboxSessionIntent.UPLOAD_FILE_S, self.need * 3))
            if (
                self.satisfaction > 0.5
                and self.need > 0.7
                and self.account.plan.successor
                and self.account.allocation_used_fraction > 0.9
            ):
                possible_intents_with_weights.append((HedgeboxSessionIntent.UPGRADE_PLAN, 0.1))
            elif self.satisfaction < 0 and self.need < 0.9 and self.account.plan.predecessor:
                possible_intents_with_weights.append((HedgeboxSessionIntent.DOWNGRADE_PLAN, 0.1))
            if self.account.plan.is_business and len(self.cluster.people) > 1:
                if len(self.account.team_members) < len(self.cluster.people):
                    possible_intents_with_weights.append((HedgeboxSessionIntent.INVITE_TEAM_MEMBER, 0.2))
                if len(self.account.team_members) > 1:
                    possible_intents_with_weights.append((HedgeboxSessionIntent.REMOVE_TEAM_MEMBER, 0.025))

        if possible_intents_with_weights:
            possible_intents, weights = zip(*possible_intents_with_weights)
            return self.cluster.random.choices(
                cast(tuple[HedgeboxSessionIntent], possible_intents),
                cast(tuple[float], weights),
            )[0]
        else:
            return None

    def simulate_session(self):
        if self.active_session_intent == HedgeboxSessionIntent.CONSIDER_PRODUCT:
            entered_url_directly = self.cluster.random.random() < 0.18
            self.active_client.register({"$referrer": "$direct" if entered_url_directly else "https://www.google.com/"})
            self.go_to_home(None if entered_url_directly else {"utm_source": "google"})
        elif self.active_session_intent == HedgeboxSessionIntent.CHECK_MARIUS_TECH_TIPS_LINK:
            entered_url_directly = self.cluster.random.random() < 0.62
            self.active_client.register(
                {"$referrer": "$direct" if entered_url_directly else "https://www.youtube.com/"}
            )
            self.go_to_marius_tech_tips(None if entered_url_directly else {"utm_source": "youtube"})
            if self.cluster.random.random() < 0.2:
                self.click_product_ad_1()
            elif self.cluster.random.random() < 0.5:
                self.click_product_ad_2()
        elif self.active_session_intent in (
            HedgeboxSessionIntent.UPLOAD_FILE_S,
            HedgeboxSessionIntent.DELETE_FILE_S,
            HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S,
            HedgeboxSessionIntent.SHARE_FILE,
            HedgeboxSessionIntent.INVITE_TEAM_MEMBER,
            HedgeboxSessionIntent.REMOVE_TEAM_MEMBER,
            HedgeboxSessionIntent.UPGRADE_PLAN,
            HedgeboxSessionIntent.DOWNGRADE_PLAN,
        ):
            entered_url_directly = self.cluster.random.random() < 0.71
            self.active_client.register({"$referrer": "$direct" if entered_url_directly else "https://www.google.com/"})

            if entered_url_directly:
                used_files_page_url = self.cluster.random.random() < 0.48
                if used_files_page_url:
                    self.go_to_files()
                else:
                    self.go_to_home()
            else:
                self.go_to_home(None if entered_url_directly else {"utm_source": "google"})
        elif self.active_session_intent == HedgeboxSessionIntent.VIEW_SHARED_FILE:
            self.active_client.register({"$referrer": "$direct"})
            if not self.file_to_view:
                raise ValueError("There's no file to view")
            self.go_to_shared_file(self.file_to_view)
            self.file_to_view = None
        elif self.active_session_intent == HedgeboxSessionIntent.JOIN_TEAM:
            self.active_client.register({"$referrer": "$direct"})
            if not self.invite_to_use_id:
                raise ValueError("There's no invite to use")
            self.go_to_invite(self.invite_to_use_id)
            self.invite_to_use_id = None
        else:
            raise ValueError(f"Unhandled session intent: {self.active_session_intent}")

    # Path directions

    def go_to_home(self, query_params=None):
        self.active_client.capture_pageview(add_params_to_url(URL_HOME, query_params))
        self.advance_timer(1.8 + self.cluster.random.betavariate(1.5, 3) * 300)  # Viewing the page
        self.satisfaction += (self.cluster.random.betavariate(1.6, 1.2) - 0.5) * 0.1  # It's a somewhat nice page
        if self.active_session_intent in (
            HedgeboxSessionIntent.UPLOAD_FILE_S,
            HedgeboxSessionIntent.DELETE_FILE_S,
            HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S,
            HedgeboxSessionIntent.SHARE_FILE,
            HedgeboxSessionIntent.INVITE_TEAM_MEMBER,
            HedgeboxSessionIntent.REMOVE_TEAM_MEMBER,
            HedgeboxSessionIntent.UPGRADE_PLAN,
            HedgeboxSessionIntent.DOWNGRADE_PLAN,
        ):
            self.enter_app()
        elif not self.has_signed_up:
            if (
                self.need > 0.4
                and self.satisfaction < 0.8
                and self.all_time_pageview_counts[URL_PRICING] < 4
                and self.cluster.random.random() < 0.8
            ):
                self.go_to_pricing()
            elif self.need > 0.5 and self.satisfaction >= 0.8 and self.cluster.random.random() < 0.6:
                self.go_to_sign_up()

    def go_to_marius_tech_tips(self, query_params=None):
        self.active_client.capture_pageview(add_params_to_url(URL_MARIUS_TECH_TIPS, query_params))
        self.advance_timer(1.2 + self.cluster.random.betavariate(1.5, 2) * 150)  # Viewing the page
        self.satisfaction += (self.cluster.random.betavariate(1.6, 1.2) - 0.5) * 0.4  # The user may be in target or not
        self.need += self.cluster.random.uniform(-0.05, 0.15)
        if self.need > 0.8 and self.satisfaction > 0:
            if self.cluster.random.random() < 0.23 and self.all_time_pageview_counts[URL_PRICING] < 3:
                self.go_to_pricing()
            elif self.all_time_pageview_counts[URL_SIGNUP] < 1:
                self.go_to_sign_up()
        elif self.need > 0.5 and self.all_time_pageview_counts[URL_HOME] < 4:
            self.go_to_home()

    def go_to_pricing(self):
        self.active_client.capture_pageview(URL_PRICING)
        self.advance_timer(1.2 + self.cluster.random.betavariate(1.5, 2) * 200)  # Viewing the page
        self.satisfaction += self.cluster.random.uniform(-0.05, self.affinity * 0.15)
        if self.satisfaction > 0:
            if self.cluster.random.random() < 0.23 and self.session_pageview_counts[URL_HOME] < 2:
                self.go_to_home()
            else:
                self.enter_app()
        elif self.need > 0.5:
            self.go_to_home()

    def go_to_sign_up(self):
        self.advance_timer(self.cluster.random.uniform(0.1, 0.2))  # Page load time

        if self.active_client.is_logged_in:
            self.go_to_files()
            return

        if not self.kernel and self.cluster.company:
            raise ValueError("Only the kernel can sign up in a company cluster")

        self.active_client.capture_pageview(URL_SIGNUP)  # Visiting the sign-up page

        if self.has_signed_up:  # Signed up already!
            self.advance_timer(5 + self.cluster.random.betavariate(2, 1.3) * 19)
            return self.go_to_login()

        # Signup is faster with the new signup page
        is_on_new_signup_page = self.decide_feature_flags().get(NEW_SIGNUP_PAGE_FLAG_KEY) == "test"
        success_rate = SIGNUP_SUCCESS_RATE_TEST if is_on_new_signup_page else SIGNUP_SUCCESS_RATE_CONTROL
        # What's the outlook?
        success = self.cluster.random.random() < success_rate
        # Looking at things, filling out forms
        self.advance_timer(
            9 + self.cluster.random.betavariate(1.2, 2) * (60 if not success else 120 if is_on_new_signup_page else 170)
        )
        # More likely to finish signing up with the new signup page
        if success:  # Let's do this!
            self.sign_up()
            self.go_to_files()
        else:  # Something didn't go right...
            self.satisfaction += (self.cluster.random.betavariate(1, 3) - 0.75) * 0.5

    def go_to_login(self):
        self.advance_timer(self.cluster.random.uniform(0.1, 0.2))  # Page load time

        if self.active_client.is_logged_in:  # Redirect to app
            self.go_to_files()
            return

        self.active_client.capture_pageview(URL_LOGIN)

        if not self.has_signed_up:  # Not signed up yet!
            self.advance_timer(3 + self.cluster.random.betavariate(1.4, 1.2) * 14)  # Need to find the Sign up button
            self.go_to_sign_up()
            return

        success = self.cluster.random.random() < 0.95  # There's always a tiny chance the user will resign
        self.advance_timer(2 + self.cluster.random.betavariate(1.2, 1.2) * (29 if success else 17))

        if success:
            self.active_client.capture(EVENT_LOGGED_IN)
            self.advance_timer(self.cluster.random.uniform(0.1, 0.2))
            self.active_client.identify(self.in_product_id)
            self.go_to_files()  # Redirect

    def go_to_files(self):
        assert self.account is not None
        self.active_client.capture_pageview(URL_FILES)
        if self.affinity < 0.2:
            # Something seriously wrong happened and now this person is pissed
            self.satisfaction += self.cluster.random.uniform(-0.6, -1.2)
        if self.active_session_intent in (
            HedgeboxSessionIntent.CONSIDER_PRODUCT,
            HedgeboxSessionIntent.UPLOAD_FILE_S,
            HedgeboxSessionIntent.DELETE_FILE_S,
            HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S,
            HedgeboxSessionIntent.SHARE_FILE,
        ):
            # Get a hang of all the files
            self.advance_timer(
                2 + self.cluster.random.betavariate(1.5, 1.2) * math.log10(0.1 + len(self.account.files))
            )
            if self.active_session_intent == HedgeboxSessionIntent.DELETE_FILE_S:
                # Sort files for deterministic selection
                file = self.cluster.random.choice(sorted(self.account.files, key=lambda f: f.id))
                self.delete_file(file)
            elif self.active_session_intent == HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S:
                # Sort files for deterministic selection
                file = self.cluster.random.choice(sorted(self.account.files, key=lambda f: f.id))
                if self.cluster.random.random() < 0.3:  # Sometimes download using the menu
                    self.download_file(file)
                else:  # Other times go to the file page first
                    self.go_to_own_file(file)
            else:
                file = HedgeboxFile(
                    id=str(self.cluster.roll_uuidt()),
                    type=self.cluster.file_provider.mime_type(),
                    size_b=int(self.cluster.random.betavariate(1.3, 3) * 7_000_000_000),
                    popularity=self.cluster.random.random(),
                )
                self.upload_file(file)
        elif self.active_session_intent in (
            HedgeboxSessionIntent.UPGRADE_PLAN,
            HedgeboxSessionIntent.DOWNGRADE_PLAN,
            HedgeboxSessionIntent.INVITE_TEAM_MEMBER,
            HedgeboxSessionIntent.REMOVE_TEAM_MEMBER,
        ):
            self.go_to_account_settings()
        else:
            raise ValueError(f"Unknown session intent {self.active_session_intent}")

    def go_to_own_file(self, file: HedgeboxFile):
        self.active_client.capture_pageview(dyn_url_file(file.id))
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 5)
        if self.active_session_intent == HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S:
            self.download_file(file)
        elif self.active_session_intent == HedgeboxSessionIntent.SHARE_FILE:
            self.share_file(file)
        elif self.active_session_intent == HedgeboxSessionIntent.DELETE_FILE_S:
            self.delete_file(file)
        random = self.cluster.random.random()
        if random < 0.2:  # Possibly go back
            self.go_to_files()
        elif random < 0.3:  # Or log out and end session
            self.log_out()

    def go_to_shared_file(self, file: HedgeboxFile):
        self.active_client.capture_pageview(dyn_url_file(file.id))
        self.advance_timer(0.5 + self.cluster.random.betavariate(1.2, 1.6) * 20)
        if self.cluster.random.random() < 0.7:
            self.active_client.capture(
                EVENT_DOWNLOADED_FILE,
                {"file_type": file.type, "file_size_b": file.size_b},
            )
        self.advance_timer(0.5 + self.cluster.random.betavariate(1.2, 2) * 80)
        self.need += (self.cluster.random.betavariate(1.2, 1) - 0.5) * 0.08
        if self.cluster.random.random() < 0.2:
            self.go_to_home()

    def go_to_account_settings(self):
        self.active_client.capture_pageview(URL_ACCOUNT_SETTINGS)
        self.advance_timer(1 + self.cluster.random.betavariate(1.2, 1.2) * 5)
        random = self.cluster.random.random()
        if (
            self.active_session_intent
            in (
                HedgeboxSessionIntent.UPGRADE_PLAN,
                HedgeboxSessionIntent.DOWNGRADE_PLAN,
            )
            or random < 0.1
        ):
            self.go_to_account_billing()
        elif (
            self.active_session_intent
            in (
                HedgeboxSessionIntent.INVITE_TEAM_MEMBER,
                HedgeboxSessionIntent.REMOVE_TEAM_MEMBER,
            )
            or random < 0.1
        ):
            self.go_to_account_team()
        elif self.session_pageview_counts[URL_FILES] < 4:
            self.go_to_files()
        # Otherwise end session

    def go_to_account_billing(self):
        self.active_client.capture_pageview(URL_ACCOUNT_BILLING)
        self.advance_timer(1 + self.cluster.random.betavariate(1.2, 1.4) * 15)
        if self.active_session_intent == HedgeboxSessionIntent.UPGRADE_PLAN:
            self.upgrade_plan()
        if self.active_session_intent == HedgeboxSessionIntent.DOWNGRADE_PLAN:
            self.downgrade_plan()

    def go_to_account_team(self):
        self.active_client.capture_pageview(URL_ACCOUNT_TEAM)
        self.advance_timer(1 + self.cluster.random.betavariate(1.2, 1.4) * 15)
        if self.active_session_intent == HedgeboxSessionIntent.INVITE_TEAM_MEMBER:
            self.invite_team_member()
        if self.active_session_intent == HedgeboxSessionIntent.REMOVE_TEAM_MEMBER:
            self.remove_team_member()

    def go_to_invite(self, invite_id: str):
        self.active_client.capture_pageview(dyn_url_invite(invite_id))
        if self.cluster.random.random() < 0.93:
            self.join_team()
            self.go_to_files()
        self.invite_to_use_id = None

    # Individual actions

    def sign_up(self):
        if self.account is not None:
            raise ValueError("Already signed up")
        self.account = HedgeboxAccount(
            id=str(self.cluster.roll_uuidt()),
            created_at=self.cluster._simulation_time,
            team_members={self},
            plan=HedgeboxPlan.PERSONAL_FREE if not self.cluster.company else HedgeboxPlan.BUSINESS_STANDARD,
        )
        self.active_client.capture(EVENT_SIGNED_UP, {"from_invite": False})
        self.advance_timer(self.cluster.random.uniform(0.1, 0.2))
        self.active_client.identify(self.in_product_id, {"email": self.email, "name": self.name})
        self.active_client.group(
            GROUP_TYPE_ACCOUNT,
            self.account.id,
            {
                "name": self.cluster.company.name if self.cluster.company else self.name,
                "industry": self.cluster.company.industry if self.cluster.company else None,
                "used_mb": 0,
                "file_count": 0,
                "plan": self.account.plan,
                "team_size": 1,
            },
        )
        self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.3) * 0.2
        self.active_session_intent = HedgeboxSessionIntent.UPLOAD_FILE_S  # Session intent changes
        self.is_invitable = False

    def join_team(self):
        if self.account is None:
            raise ValueError("Cannot join team without an account")
        self.active_client.capture(EVENT_SIGNED_UP, {"from_invite": True})
        self.advance_timer(self.cluster.random.uniform(0.1, 0.2))
        self.active_client.group(
            GROUP_TYPE_ACCOUNT,
            self.account.id,
            {"team_size": len(self.account.team_members)},
        )
        self.account.team_members.add(self)

    def upload_file(self, file: HedgeboxFile):
        assert self.account is not None
        self.advance_timer(self.cluster.random.betavariate(2.5, 1.1) * 95)
        self.account.files.add(file)
        self.active_client.capture(
            EVENT_UPLOADED_FILE,
            properties={
                "file_type": file.type,
                "file_size_b": file.size_b,
                "used_mb": self.account.current_used_mb,
            },
        )
        self.active_client.group(
            GROUP_TYPE_ACCOUNT,
            self.account.id,
            {
                "used_mb": self.account.current_used_mb,
                "file_count": len(self.account.files),
            },
        )
        self.satisfaction += self.cluster.random.uniform(-0.19, 0.2)
        if self.satisfaction > 0.9:
            self.schedule_effect(
                self.cluster.simulation_time,
                lambda other: other.move_attribute("need", 0.05),
                Effect.Target.ALL_NEIGHBORS,
            )

    def download_file(self, file: HedgeboxFile):
        self.active_client.capture(EVENT_DOWNLOADED_FILE, {"file_type": file.type, "file_size_b": file.size_b})

    def delete_file(self, file: HedgeboxFile):
        assert self.account is not None
        self.account.files.remove(file)
        self.active_client.capture(EVENT_DELETED_FILE, {"file_type": file.type, "file_size_b": file.size_b})
        self.active_client.group(
            GROUP_TYPE_ACCOUNT,
            self.account.id,
            {
                "used_mb": self.account.current_used_mb,
                "file_count": len(self.account.files),
            },
        )

    def share_file(self, file: HedgeboxFile):
        self.active_client.capture(EVENT_SHARED_FILE_LINK, {"file_type": file.type, "file_size_b": file.size_b})
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        self.schedule_effect(
            self.cluster.simulation_time,
            lambda other: other.set_attribute("file_to_view", file),
            Effect.Target.RANDOM_NEIGHBOR,
        )

    def upgrade_plan(self):
        assert self.account is not None
        previous_plan = self.account.plan
        new_plan = previous_plan.successor
        if new_plan is None:
            raise ValueError("There's no successor plan")
        self.active_client.capture(
            EVENT_UPGRADED_PLAN,
            {"previous_plan": str(previous_plan), "new_plan": str(new_plan)},
        )
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        self.schedule_effect(
            self.cluster.simulation_time,
            lambda other: other.move_attribute("satisfaction", 0.03),
            Effect.Target.ALL_NEIGHBORS,
        )
        self.account.plan = new_plan
        if not self.account.was_billing_scheduled:
            self.account.was_billing_scheduled = True
            future_months = math.ceil(
                (self.cluster.end.astimezone(ZoneInfo(self.timezone)) - self.cluster.simulation_time).days / 30
            )
            for i in range(future_months):
                bill_timestamp = self.cluster.simulation_time + dt.timedelta(days=30 * i)
                self.schedule_effect(
                    bill_timestamp,
                    lambda person: person.bill_account(),
                    Effect.Target.SELF,
                )

    def downgrade_plan(self):
        assert self.account is not None
        previous_plan = self.account.plan
        new_plan = previous_plan.predecessor
        if new_plan is None:
            raise ValueError("There's no predecessor plan")
        self.active_client.capture(
            EVENT_DOWNGRADED_PLAN,
            {"previous_plan": str(previous_plan), "new_plan": str(new_plan)},
        )
        self.account.plan = new_plan

    def invite_team_member(self):
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        self.active_client.capture(EVENT_INVITED_TEAM_MEMBER)
        invite_id = str(self.cluster.roll_uuidt())
        self.schedule_effect(
            self.cluster.simulation_time,
            lambda other: other.set_attribute("invite_to_use_id", invite_id)
            and other.set_attribute("is_invitable", False),
            Effect.Target.RANDOM_NEIGHBOR,
            condition=lambda other: cast(HedgeboxPerson, other).is_invitable,
        )

    def remove_team_member(self):
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        assert self.account is not None
        # Sort team members for deterministic selection
        eligible_members = self.account.team_members.difference({self, self.cluster.kernel})
        random_member = self.cluster.random.choice(sorted(eligible_members, key=lambda p: p.in_product_id))
        self.account.team_members.remove(random_member)
        self.active_client.capture(EVENT_REMOVED_TEAM_MEMBER)

    def bill_account(self):
        if self.account and self.account.current_monthly_bill_usd:
            self.cluster.matrix.server_client.capture(
                EVENT_PAID_BILL,
                {
                    "amount_usd": self.account.current_monthly_bill_usd,
                    "plan": self.account.plan,
                },
                distinct_id=self.in_product_id,
            )

    def enter_app(self):
        if not self.has_signed_up:
            self.go_to_sign_up()
        elif not self.active_client.is_logged_in:
            self.go_to_login()
        else:
            self.go_to_files()

    def log_out(self):
        self.active_client.capture(EVENT_LOGGED_OUT)
        self.active_client.reset()
        self.advance_timer(self.cluster.random.uniform(0.1, 0.2))

    @property
    def invitable_neighbors(self) -> list["HedgeboxPerson"]:
        return [
            neighbor
            for neighbor in cast(list[HedgeboxPerson], self.cluster.list_neighbors(self))
            if neighbor.is_invitable
        ]

    def click_product_ad_1(self):
        self.active_client.capture(
            EVENT_AUTOCAPTURE, {"$event_type": "click", "$external_click_url": URL_PRODUCT_AD_LINK_1}
        )

    def click_product_ad_2(self):
        self.active_client.capture(
            EVENT_AUTOCAPTURE, {"$event_type": "click", "$external_click_url": URL_PRODUCT_AD_LINK_2}
        )


def add_params_to_url(url, query_params):
    if not query_params:
        return url
    parsed_url = urlparse(url)
    encoded_query = urlencode(query_params)
    new_query = f"{parsed_url.query}&{encoded_query}" if parsed_url.query else encoded_query
    return urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment)
    )
