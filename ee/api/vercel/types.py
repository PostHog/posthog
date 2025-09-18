from dataclasses import dataclass
from typing import Literal, Union

from django.contrib.auth.models import AnonymousUser


@dataclass
class VercelBaseClaims:
    iss: str
    sub: str
    aud: str
    account_id: str
    installation_id: str
    type: Literal["access_token", "id_token"] | None


@dataclass
class VercelUserClaims(VercelBaseClaims):
    user_id: str
    user_role: Literal["ADMIN", "USER"]
    user_avatar_url: str | None
    user_email: str | None  # Only available if integration is opted in (Which it is in our case)
    user_name: str | None


@dataclass
class VercelSystemClaims(VercelBaseClaims):
    pass


VercelClaims = Union[VercelUserClaims, VercelSystemClaims]


class VercelUser(AnonymousUser):
    def __init__(self, claims: VercelClaims):
        super().__init__()
        self.claims = claims
