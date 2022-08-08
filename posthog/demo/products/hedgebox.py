import datetime as dt
import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, cast

import pytz

from posthog.constants import INSIGHT_TRENDS, TRENDS_LINEAR, TRENDS_WORLD_MAP
from posthog.demo.matrix.matrix import Cluster, Matrix
from posthog.demo.matrix.models import SimPerson, SimSessionIntent
from posthog.models import Cohort, Dashboard, DashboardTile, Experiment, FeatureFlag, Insight, InsightViewed

# This is a simulation of an online drive SaaS called Hedgebox
# See this RFC for the reasoning behind it:
# https://github.com/PostHog/product-internal/blob/main/requests-for-comments/2022-03-23-great-demo-data.md

# Simulation features:
# - the product is used by lots of personal users, but businesses bring the most revenue
# - most users are from the US, but there are blips all over the world
# - timezones are accurate on the country level
# - usage times are accurate taking into account time of day, timezone, and user profile (personal or business)
# - Hedgebox is sponsoring the well-known YouTube channel about technology Marius Tech Tips - there's a landing page
# - an experiment with a new signup page is running, and it's showing positive results
# - Internet Explorer users do worse

# See this flowchart for the layout of the product:
# https://www.figma.com/file/nmvylkFx4JdTRDqyo5Vkb5/Hedgebox-Paths

# URLs

SITE_URL = "https://hedgebox.net"

URL_HOME = f"{SITE_URL}/"
URL_MARIUS_TECH_TIPS = f"{SITE_URL}/mariustechtips/"
URL_PRICING = f"{SITE_URL}/pricing/"

URL_SIGNUP = f"{SITE_URL}/signup/"
URL_LOGIN = f"{SITE_URL}/login/"
dyn_url_invite = lambda invite_id: f"{SITE_URL}/invite/{invite_id}/"

URL_FILES = f"{SITE_URL}/files/"
dyn_url_file = lambda file_id: f"{SITE_URL}/files/{file_id}/"

URL_ACCOUNT_SETTINGS = f"{SITE_URL}/account/settings/"
URL_ACCOUNT_BILLING = f"{SITE_URL}/account/billing/"
URL_ACCOUNT_TEAM = f"{SITE_URL}/account/team/"

# Event taxonomy

EVENT_SIGNED_UP = "signed_up"  # Properties: from_invite
EVENT_LOGGED_IN = "logged_in"  # No extra properties
EVENT_LOGGED_OUT = "logged_out"  # No extra properties

EVENT_UPLOADED_FILE = "uploaded_file"  # Properties: file_type, file_size_b
EVENT_DOWNLOADED_FILE = "downloaded_file"  # Properties: file_type, file_size_b
EVENT_DELETED_FILE = "deleted_file"  # Properties: file_type, file_size_b
EVENT_SHARED_FILE_LINK = "shared_file_link"  # Properties: file_type, file_size_b

EVENT_UPGRADED_PLAN = "upgraded_plan"  # Properties: previous_plan, new_plan
EVENT_DOWNGRADED_PLAN = "downgraded_plan"  # Properties: previous_plan, new_plan

EVENT_INVITED_TEAM_MEMBER = "invited_team_member"  # No extra properties
EVENT_REMOVED_TEAM_MEMBER = "removed_team_member"  # No extra properties

EVENT_PAID_BILL = "paid_bill"  # Properties: plan, amount_usd

# Group taxonomy

GROUP_TYPE_ACCOUNT = "account"  # Properties: name, used_mb, plan, team_size

# Feature flags

FILE_PREVIEWS_FLAG_KEY = "file-previews"
NEW_SIGNUP_PAGE_FLAG_KEY = "signup-page-4.0"
NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT = 50
PROPERTY_NEW_SIGNUP_PAGE_FLAG = f"$feature/{NEW_SIGNUP_PAGE_FLAG_KEY}"
SIGNUP_SUCCESS_RATE_TEST = 0.5794
SIGNUP_SUCCESS_RATE_CONTROL = 0.4887

# World properties

# How many clusters should be companies (made up of business users) as opposed to social circles (personal users)
COMPANY_CLUSTERS_PROPORTION = 0.2


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


class HedgeboxPlan(str, Enum):
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
    team_members: Set["HedgeboxPerson"]
    plan: HedgeboxPlan = field(default=HedgeboxPlan.PERSONAL_FREE)
    files: Set[HedgeboxFile] = field(default_factory=set)
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
    def current_monthly_bill_usd(self) -> Decimal:
        if self.plan == HedgeboxPlan.PERSONAL_FREE:
            return Decimal("0.00")
        elif self.plan == HedgeboxPlan.PERSONAL_PRO:
            return Decimal("10.00")
        elif self.plan == HedgeboxPlan.BUSINESS_STANDARD:
            return Decimal("10.00") * len(self.team_members)
        elif self.plan == HedgeboxPlan.BUSINESS_ENTERPRISE:
            return Decimal("20.00") * len(self.team_members)
        else:
            raise ValueError(f"Unknown plan: {self.plan}")


class HedgeboxPerson(SimPerson):
    cluster: "HedgeboxCluster"

    # Constant properties
    person_id: str
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
    _personal_account: Optional[HedgeboxAccount]  # In company clusters the cluster-level account is used

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.person_id = self.cluster.random.randstr(False, 16)
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
        self._personal_account = None
        while True:
            self.country_code = (
                "US" if self.cluster.random.random() < 0.9132 else self.cluster.address_provider.country_code()
            )
            try:  # Some tiny regions aren't in pytz - we want to omit those
                self.timezone = self.cluster.random.choice(pytz.country_timezones[self.country_code])
            except KeyError:
                continue
            else:
                break

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def __hash__(self) -> int:
        return hash(self.person_id)

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
        return self.cluster._business_account if self.cluster.company_name else self._personal_account

    @account.setter
    def account(self, value):
        if self.cluster.company_name:
            self.cluster._business_account = value
        else:
            self._personal_account = value

    @property
    def has_signed_up(self) -> bool:
        return self.account is not None and self in self.account.team_members

    # Abstract methods

    def decide_feature_flags(self) -> Dict[str, Any]:
        if (
            self.simulation_time >= self.cluster.matrix.new_signup_page_experiment_start
            and self.simulation_time < self.cluster.matrix.new_signup_page_experiment_end
        ):
            return {NEW_SIGNUP_PAGE_FLAG_KEY: "test" if self.falls_into_new_signup_page_bucket else "control"}
        else:
            return {}

    def determine_next_session_datetime(self) -> dt.datetime:
        next_session_datetime = self.simulation_time
        while True:
            next_session_datetime += dt.timedelta(
                seconds=self.cluster.random.betavariate(2.5, 1 + self.need)
                * (36_000 if self.has_signed_up else 172_800)
                + 24,
            )
            time_appropriateness: float
            # Check if it's night
            if 5 < next_session_datetime.hour < 23:
                time_appropriateness = 0.1
            # Check if it's 9 to 5 on a work day
            elif next_session_datetime.weekday() <= 5 and 9 <= next_session_datetime.hour <= 17:
                # Business users most likely to be active during the work day, personal users just the opposite
                time_appropriateness = 1 if self.cluster.company_name else 0.3
            else:
                time_appropriateness = 0.2 if self.cluster.company_name else 1

            if self.cluster.random.random() < time_appropriateness:
                return next_session_datetime  # If the time is right, let's act - otherwise, let's advance further

    def determine_session_intent(self) -> Optional[HedgeboxSessionIntent]:
        if self.affinity < 0.1 or not self.kernel and self.cluster.company_name:
            # Very low affinity users aren't interested
            # Non-kernel business users can't log in or sign up
            return None
        possible_intents_with_weights: List[Tuple[HedgeboxSessionIntent, float]] = []
        if self.invite_to_use_id:
            possible_intents_with_weights.append((HedgeboxSessionIntent.JOIN_TEAM, 1))
        elif self.file_to_view:
            possible_intents_with_weights.append((HedgeboxSessionIntent.VIEW_SHARED_FILE, 1))
        elif not self.has_signed_up:
            if self.all_time_pageview_counts[URL_HOME] < 2:
                possible_intents_with_weights.append((HedgeboxSessionIntent.CONSIDER_PRODUCT, 2),)
            if self.watches_marius_tech_tips and not self.all_time_pageview_counts[URL_MARIUS_TECH_TIPS]:
                possible_intents_with_weights.append((HedgeboxSessionIntent.CHECK_MARIUS_TECH_TIPS_LINK, 1),)
        else:
            account = cast(HedgeboxAccount, self.account)  # Must exist in this branch
            file_count = len(account.files)
            # The more files, the more likely to delete/download/share rather than upload
            possible_intents_with_weights.extend(
                [
                    (HedgeboxSessionIntent.DELETE_FILE_S, math.log10(file_count) / 8 if file_count else 0),
                    (HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S, math.log10(file_count + 1) if file_count else 0),
                    (HedgeboxSessionIntent.SHARE_FILE, math.log10(file_count) / 3 if file_count else 0),
                ]
            )
            if account.allocation_used_fraction < 0.99:
                possible_intents_with_weights.append((HedgeboxSessionIntent.UPLOAD_FILE_S, self.need * 3))
            if (
                self.satisfaction > 0.5
                and self.need > 0.7
                and account.plan.successor
                and account.allocation_used_fraction > 0.9
            ):
                possible_intents_with_weights.append((HedgeboxSessionIntent.UPGRADE_PLAN, 0.1))
            elif self.satisfaction < -0.5 and self.need < 0.9 and account.plan.predecessor:
                possible_intents_with_weights.append((HedgeboxSessionIntent.DOWNGRADE_PLAN, 0.1))
            if account.plan.is_business and len(self.cluster.people) > 1:
                if len(account.team_members) < len(self.cluster.people):
                    possible_intents_with_weights.append((HedgeboxSessionIntent.INVITE_TEAM_MEMBER, 0.2))
                if len(account.team_members) > 1:
                    possible_intents_with_weights.append((HedgeboxSessionIntent.REMOVE_TEAM_MEMBER, 0.025))

        if possible_intents_with_weights:
            possible_intents, weights = zip(*possible_intents_with_weights)
            return self.cluster.random.choices(
                cast(Tuple[HedgeboxSessionIntent], possible_intents), cast(Tuple[float], weights)
            )[0]
        else:
            return None

    def simulate_session(self):
        if self.active_session_intent == HedgeboxSessionIntent.CONSIDER_PRODUCT:
            entered_url_directly = self.cluster.random.random() < 0.18
            self.active_client.register({"$referrer": "$direct" if entered_url_directly else "https://www.google.com/"})
            self.go_to_home()
        elif self.active_session_intent == HedgeboxSessionIntent.CHECK_MARIUS_TECH_TIPS_LINK:
            entered_url_directly = self.cluster.random.random() < 0.62
            self.active_client.register(
                {"$referrer": "$direct" if entered_url_directly else "https://www.youtube.com/"}
            )
            self.go_to_marius_tech_tips()
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
                self.go_to_home()
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

    def go_to_home(self):
        self.active_client.capture_pageview(URL_HOME)
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

    def go_to_marius_tech_tips(self):
        self.active_client.capture_pageview(URL_MARIUS_TECH_TIPS)
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

        if not self.kernel and self.cluster.company_name:
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
            self.active_client.identify(self.person_id)
            self.go_to_files()  # Redirect

    def go_to_files(self):
        account = cast(HedgeboxAccount, self.account)
        self.active_client.capture_pageview(URL_FILES)
        if self.active_session_intent in (
            HedgeboxSessionIntent.CONSIDER_PRODUCT,
            HedgeboxSessionIntent.UPLOAD_FILE_S,
            HedgeboxSessionIntent.DELETE_FILE_S,
            HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S,
            HedgeboxSessionIntent.SHARE_FILE,
        ):
            # Get a hang of all the files
            self.advance_timer(2 + self.cluster.random.betavariate(1.5, 1.2) * math.log10(0.1 + len(account.files)))
            if self.active_session_intent == HedgeboxSessionIntent.DELETE_FILE_S:
                file = self.cluster.random.choice(list(account.files))
                self.delete_file(file)
            elif self.active_session_intent == HedgeboxSessionIntent.DOWNLOAD_OWN_FILE_S:
                file = self.cluster.random.choice(list(account.files))
                if self.cluster.random.random() < 0.3:  # Sometimes download using the menu
                    self.download_file(file)
                else:  # Other times go to the file page first
                    self.go_to_own_file(file)
            else:
                file = HedgeboxFile(
                    id=str(self.roll_uuidt()),
                    type=self.cluster.file_provider.mime_type(),
                    size_b=int(self.cluster.random.betavariate(1.3, 3) * 7_000_000_000),
                    popularity=self.cluster.random.random(),
                )
                self.upload_file(file)

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
            self.active_client.capture(EVENT_DOWNLOADED_FILE, {"file_type": file.type, "file_size_b": file.size_b})
        self.advance_timer(0.5 + self.cluster.random.betavariate(1.2, 2) * 80)
        self.need += (self.cluster.random.betavariate(1.2, 1) - 0.5) * 0.08
        if self.cluster.random.random() < 0.2:
            self.go_to_home()

    def go_to_account_settings(self):
        self.active_client.capture_pageview(URL_ACCOUNT_SETTINGS)
        self.advance_timer(1 + self.cluster.random.betavariate(1.2, 1.2) * 5)
        random = self.cluster.random.random()
        if (
            self.active_session_intent in (HedgeboxSessionIntent.UPGRADE_PLAN, HedgeboxSessionIntent.DOWNGRADE_PLAN)
            or random < 0.1
        ):
            self.go_to_account_billing()
        elif (
            self.active_session_intent
            in (HedgeboxSessionIntent.INVITE_TEAM_MEMBER, HedgeboxSessionIntent.REMOVE_TEAM_MEMBER)
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
        self.account = HedgeboxAccount(id=str(self.roll_uuidt()), team_members={self})  # TODO: Add billing
        self.active_client.capture(EVENT_SIGNED_UP, {"from_invite": False})
        self.advance_timer(self.cluster.random.uniform(0.1, 0.2))
        self.active_client.identify(self.person_id, {"email": self.email, "name": self.name})
        self.active_client.group(
            GROUP_TYPE_ACCOUNT,
            self.account.id,
            {"name": self.cluster.company_name or self.name, "used_mb": 0, "plan": self.account.plan, "team_size": 1,},
        )
        self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.3) * 0.2
        self.active_session_intent = HedgeboxSessionIntent.UPLOAD_FILE_S  # Session intent changes
        self.is_invitable = False

    def join_team(self):
        if self.account is None:
            raise ValueError("Cannot join team without an account")
        self.active_client.capture(EVENT_SIGNED_UP, {"from_invite": True})
        self.advance_timer(self.cluster.random.uniform(0.1, 0.2))
        self.active_client.group(GROUP_TYPE_ACCOUNT, self.account.id, {"team_size": len(self.account.team_members)})
        self.account.team_members.add(self)

    def upload_file(self, file: HedgeboxFile):
        self.advance_timer(self.cluster.random.betavariate(2.5, 1.1) * 95)
        cast(HedgeboxAccount, self.account).files.add(file)
        self.active_client.capture(
            EVENT_UPLOADED_FILE, properties={"file_type": file.type, "file_size_b": file.size_b},
        )
        self.satisfaction += self.cluster.random.uniform(-0.19, 0.2)
        if self.satisfaction > 0.9:
            self.affect_all_neighbors(lambda other: other.move_attribute("need", 0.05))

    def download_file(self, file: HedgeboxFile):
        self.active_client.capture(EVENT_DOWNLOADED_FILE, {"file_type": file.type, "file_size_b": file.size_b})

    def delete_file(self, file: HedgeboxFile):
        cast(HedgeboxAccount, self.account).files.remove(file)
        self.active_client.capture(EVENT_DELETED_FILE, {"file_type": file.type, "file_size_b": file.size_b})

    def share_file(self, file: HedgeboxFile):
        self.active_client.capture(EVENT_SHARED_FILE_LINK, {"file_type": file.type, "file_size_b": file.size_b})
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        self.affect_random_neighbor(lambda other: other.set_attribute("file_to_view", file))

    def upgrade_plan(self):
        account = cast(HedgeboxAccount, self.account)
        previous_plan = account.plan
        new_plan = previous_plan.successor
        if new_plan is None:
            raise ValueError("There's no successor plan")
        self.active_client.capture(
            EVENT_UPGRADED_PLAN, {"previous_plan": str(previous_plan), "new_plan": str(new_plan),}
        )
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        self.affect_all_neighbors(lambda other: other.move_attribute("satisfaction", 0.03))
        account.plan = new_plan
        if not account.was_billing_scheduled:
            account.was_billing_scheduled = True
            future_months = math.ceil(
                (self.cluster.end.astimezone(pytz.timezone(self.timezone)) - self.simulation_time).days / 30
            )
            for i in range(future_months):
                bill_timestamp = self.simulation_time + dt.timedelta(days=30 * i)
                self.schedule_effect(bill_timestamp, lambda person: person.bill_account(bill_timestamp))

    def downgrade_plan(self):
        account = cast(HedgeboxAccount, self.account)
        previous_plan = account.plan
        new_plan = previous_plan.predecessor
        if new_plan is None:
            raise ValueError("There's no predecessor plan")
        self.active_client.capture(
            EVENT_DOWNGRADED_PLAN, {"previous_plan": str(previous_plan), "new_plan": str(new_plan),}
        )
        account.plan = new_plan

    def invite_team_member(self):
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        self.active_client.capture(EVENT_INVITED_TEAM_MEMBER)
        invite_id = str(self.roll_uuidt())
        self.affect_random_neighbor(
            lambda other: other.set_attribute("invite_to_use_id", invite_id)
            and other.set_attribute("is_invitable", False),
            condition=lambda other: cast(HedgeboxPerson, other).is_invitable,
        )

    def remove_team_member(self):
        self.advance_timer(self.cluster.random.betavariate(1.2, 1.2) * 2)
        account = cast(HedgeboxAccount, self.account)
        random_member = self.cluster.random.choice(list(account.team_members.difference({self, self.cluster.kernel})))
        account.team_members.remove(random_member)
        self.active_client.capture(EVENT_REMOVED_TEAM_MEMBER)

    def bill_account(self):
        if self.account and self.account.current_monthly_bill_usd:
            self.cluster.matrix.server_client.capture(
                EVENT_PAID_BILL,
                {"amount_usd": self.account.current_monthly_bill_usd, "plan": self.account.plan},
                distinct_id=self.person_id,
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
    def invitable_neighbors(self) -> List["HedgeboxPerson"]:
        return [
            neighbor
            for neighbor in cast(List[HedgeboxPerson], self.cluster._list_amenable_neighbors(self.x, self.y))
            if neighbor.is_invitable
        ]


class HedgeboxCluster(Cluster):
    matrix: "HedgeboxMatrix"

    MIN_RADIUS: int = 0
    MAX_RADIUS: int = 6

    # Properties
    company_name: Optional[str]  # None means the cluster is a social circle instead of a company

    # Internal state - plain
    _business_account: Optional[HedgeboxAccount]  # In social circle clusters the person-level account is used

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_company = self.random.random() < COMPANY_CLUSTERS_PROPORTION
        self.company_name = self.finance_provider.company() if is_company else None
        self._business_account = None

    def __str__(self) -> str:
        return self.company_name or f"Social Circle #{self.index+1}"

    def radius_distribution(self) -> float:
        return self.random.betavariate(1.5, 5)

    def initation_distribution(self) -> float:
        return self.random.betavariate(1.8, 1)


class HedgeboxMatrix(Matrix):
    PRODUCT_NAME = "Hedgebox"
    CLUSTER_CLASS = HedgeboxCluster
    PERSON_CLASS = HedgeboxPerson

    new_signup_page_experiment_start: dt.datetime
    new_signup_page_experiment_end: dt.datetime

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Start new signup page experiment roughly halfway through the simulation, end soon before `now`
        self.new_signup_page_experiment_end = self.now - dt.timedelta(days=2, hours=3, seconds=43)
        self.new_signup_page_experiment_start = self.start + (self.new_signup_page_experiment_end - self.start) / 2

    def set_project_up(self, team, user):
        super().set_project_up(team, user)

        # Dashboard: Key metrics (project home)
        key_metrics_dashboard = Dashboard.objects.create(
            team=team, name="🔑 Key metrics", description="Company overview.", pinned=True
        )
        team.primary_dashboard = key_metrics_dashboard
        weekly_signups_insight = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Weekly signups",
            filters={
                "events": [{"id": EVENT_SIGNED_UP, "type": "events", "order": 0}],
                "actions": [],
                "display": TRENDS_LINEAR,
                "insight": INSIGHT_TRENDS,
                "interval": "week",
                "date_from": "-1m",
            },
            last_modified_at=self.now - dt.timedelta(days=23),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=weekly_signups_insight,
            color="blue",
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )
        signups_by_country_insight = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Last month's signups by country",
            filters={
                "events": [{"id": EVENT_SIGNED_UP, "type": "events", "order": 0}],
                "actions": [],
                "display": TRENDS_WORLD_MAP,
                "insight": INSIGHT_TRENDS,
                "breakdown_type": "event",
                "breakdown": "$geoip_country_code",
                "date_from": "-1m",
            },
            last_modified_at=self.now - dt.timedelta(days=6),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=signups_by_country_insight,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )
        signup_from_homepage_funnel = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Homepage view to signup conversion",
            filters={
                "events": [
                    {
                        "custom_name": "Viewed homepage",
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "https://hedgebox.net/",
                                "operator": "exact",
                            }
                        ],
                    },
                    {
                        "custom_name": "Viewed signup page",
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 1,
                        "properties": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "https:\\/\\/hedgebox\\.net\\/register($|\\/)",
                                "operator": "regex",
                            }
                        ],
                    },
                    {"custom_name": "Signed up", "id": "signed_up", "name": "signed_up", "type": "events", "order": 2},
                ],
                "actions": [],
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "funnel_viz_type": "steps",
                "filter_test_accounts": True,
                "date_from": "-1m",
            },
            last_modified_at=self.now - dt.timedelta(days=19),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=signup_from_homepage_funnel,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )
        weekly_uploader_retention = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Weekly uploader retention",
            filters={
                "period": "Week",
                "display": "ActionsTable",
                "insight": "RETENTION",
                "properties": [],
                "target_entity": {"id": "uploaded_file", "name": "uploaded_file", "type": "events", "order": 0},
                "retention_type": "retention_first_time",
                "total_intervals": 11,
                "returning_entity": {"id": "uploaded_file", "name": "uploaded_file", "type": "events", "order": 0},
                "filter_test_accounts": True,
            },
            last_modified_at=self.now - dt.timedelta(days=34),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=weekly_uploader_retention,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )

        # InsightViewed
        InsightViewed.objects.bulk_create(
            (
                InsightViewed(
                    team=team,
                    user=user,
                    insight=insight,
                    last_viewed_at=(
                        self.now - dt.timedelta(days=self.random.randint(0, 3), minutes=self.random.randint(5, 60))
                    ),
                )
                for insight in Insight.objects.filter(team=team)
            )
        )
        # Cohorts
        Cohort.objects.create(
            team=team,
            name="Signed-up users",
            created_by=user,
            groups=[{"properties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}]}],
        )
        real_users_cohort = Cohort.objects.create(
            team=team,
            name="Real users",
            description="People who don't belong to the Hedgebox team.",
            created_by=user,
            groups=[
                {"properties": [{"key": "email", "type": "person", "value": "@hedgebox.net$", "operator": "not_regex"}]}
            ],
        )
        team.test_account_filters = [{"key": "id", "type": "cohort", "value": real_users_cohort.pk}]

        # Feature flags
        new_signup_page_flag = FeatureFlag.objects.create(
            team=team,
            key=FILE_PREVIEWS_FLAG_KEY,
            name="File previews (ticket #2137). Work-in-progress, so only visible internally at the moment",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": [
                                    "mark.s@hedgebox.net",
                                    "helly.r@hedgebox.net",
                                    "irving.b@hedgebox.net",
                                    "dylan.g@hedgebox.net",
                                ],
                                "operator": "exact",
                            }
                        ]
                    }
                ]
            },
            created_by=user,
            created_at=self.now - dt.timedelta(days=15),
        )

        # Experiments
        new_signup_page_flag = FeatureFlag.objects.create(
            team=team,
            key=NEW_SIGNUP_PAGE_FLAG_KEY,
            name="New sign-up flow",
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                        {"key": "test", "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                    ]
                },
            },
            created_by=user,
            created_at=self.new_signup_page_experiment_start - dt.timedelta(hours=1),
        )
        Experiment.objects.create(
            team=team,
            name="New sign-up flow",
            description="We've rebuilt our sign-up page to offer a more personalized experience. Let's see if this version performs better with potential users.",
            feature_flag=new_signup_page_flag,
            created_by=user,
            filters={
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "https:\\/\\/hedgebox\\.net\\/register($|\\/)",
                                "operator": "regex",
                            }
                        ],
                    },
                    {"id": "signed_up", "name": "signed_up", "type": "events", "order": 1},
                ],
                "actions": [],
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "funnel_viz_type": "steps",
                "filter_test_accounts": True,
            },
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                    {"key": "test", "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.43),
                "recommended_running_time": None,
                "minimum_detectable_effect": 1,
            },
            start_date=self.new_signup_page_experiment_start,
            end_date=self.new_signup_page_experiment_end,
            created_at=new_signup_page_flag.created_at,
        )
