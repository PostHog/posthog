from typing import Literal, NotRequired, TypedDict, Union

from django.contrib.auth.models import AnonymousUser


class VercelBaseClaims(TypedDict):
    iss: str
    sub: str
    aud: str
    account_id: str
    installation_id: str
    type: NotRequired[Literal["access_token", "id_token"]]


class VercelUserClaims(VercelBaseClaims):
    user_id: str
    user_role: Literal["ADMIN", "USER"]
    user_avatar_url: NotRequired[str]
    user_email: NotRequired[str]  # Only available if integration is opted in (Which it is in our case)
    user_name: NotRequired[str]


class VercelSystemClaims(VercelBaseClaims):
    pass


VercelClaims = Union[VercelUserClaims, VercelSystemClaims]


class VercelUser(AnonymousUser):
    def __init__(self, claims: VercelClaims):
        super().__init__()
        self.claims = claims
