import datetime as dt
from typing import Literal, Optional

from posthog.models.utils import UUIDT

from .matrix.matrix import Cluster, Matrix
from .matrix.models import SimPerson

# Event name constants
EVENT_SIGNED_UP = "signed_up"
EVENT_PAID_BILL = "paid_bill"


class HedgeboxPerson(SimPerson):
    need: float  # Need for the product
    satisfaction: float  # -1 means hate, 0 means neutrality, 1 means love
    usage_profile: float  # 0 means fully personal use intentions, 1 means fully professional
    plan: Optional[Literal[0, 1, 2]]  # None means person has no account, 0 means free, 1 means 100 GB, 2 means 1 TB

    name: str
    email: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.need = self.cluster.random.uniform(0.7 if self.kernel else 0, 1 if self.kernel else 0.08)
        self.satisfaction = 0.0
        self.usage_profile = self.cluster.random.betavariate(1, 2)  # Most users skew personal
        self.plan = None
        self.name = self.cluster.person_provider.full_name()
        self.email = self.cluster.person_provider.email()

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def _simulate_session(self):
        self.active_client.start_session(
            str(UUIDT(int(self.simulation_time.timestamp()), seeded_random=self.cluster.random))
        )
        if self.plan is None and self.need > 0.5:
            capture_pageleave = self._capture_pageview("https://hedgebox.net/")  # Homepage!
            self._advance_timer(0.5 + self.cluster.random.betavariate(1.1, 1.5) * 80)  # Viewing the page
            self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.2) * 0.15  # It's a nice page
            if self.satisfaction > 0:
                capture_pageleave()
                self._consider_signing_up()
        self.simulation_time += dt.timedelta(days=365 * 100)

    # Individual flows

    def _consider_signing_up(self):
        """Go through sign-up flow and return True if the user signed up."""
        capture_pageleave = self._capture_pageview("https://hedgebox.net/register/")  # Visiting the sign-up page
        self._advance_timer(15 + self.cluster.random.betavariate(1.1, 2) * 70)  # Looking at things, filling out forms
        success = self.cluster.random.random() < 0.7
        if success:  # Let's do this!
            self._capture(EVENT_SIGNED_UP, current_url="https://hedgebox.net/register/")
            self._advance_timer(self.cluster.random.uniform(0.1, 0.2))
            self._identify(self.email)
            self.has_signed_up = 0
            self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.5) * 0.2
        else:  # Something didn't go right...
            self.satisfaction += (self.cluster.random.betavariate(1, 3) - 0.5) * 0.2
        capture_pageleave()
        return success

    def _consider_uploading_files(self):
        pass

    def _consider_downloading_files(self):
        pass

    def _share_file_link(self):
        pass

    def _receive_file_link(self):
        pass

    def _upgrade_plan(self):
        pass

    def _downgrade_plan(self):
        pass

    def _recommend_product(self):
        pass


class HedgeboxCluster(Cluster):
    MIN_RADIUS: int = 1
    MAX_RADIUS: int = 6

    company_name: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.company_name = self.finance_provider.company()

    def __str__(self) -> str:
        return self.company_name

    def radius_distribution(self) -> int:
        return int(self.MIN_RADIUS + self.random.betavariate(1.5, 5) * (self.MAX_RADIUS - self.MIN_RADIUS))


class HedgeboxMatrix(Matrix):
    person_model = HedgeboxPerson
    cluster_model = HedgeboxCluster

    def set_project_up(self, team, user):
        pass
