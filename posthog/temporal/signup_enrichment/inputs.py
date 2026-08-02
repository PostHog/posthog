"""Workflow input dataclass, kept separate from workflow.py so the signup request path
(posthog/api/signup.py -> trigger.py) can depend on it without pulling in the Temporal
workflow/activity definitions and their products.growth/ee enrichment provider chain.
"""

import typing
import dataclasses


@dataclasses.dataclass
class SignupEnrichmentInputs:
    organization_id: str
    distinct_id: str
    domain: str
    # The signup's own role answer, passed at dispatch rather than re-read org-side. Defaulted so
    # workflows already sleeping through the recheck delay at deploy still deserialize.
    role_at_organization: typing.Optional[str] = None
    # The signup request's GeoIP country (ISO alpha-2), the score's country fallback when the
    # provider has none — mirroring the incumbent icp_country merge order. Defaulted for the
    # same deserialization reason as role_at_organization.
    geoip_country_code: typing.Optional[str] = None
