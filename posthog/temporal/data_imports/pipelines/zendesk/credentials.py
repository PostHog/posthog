"""
This module handles how credentials are read in dlt sources
"""

from typing import ClassVar, Union
import dlt
from dlt.common.configuration import configspec
from dlt.common.configuration.specs import CredentialsConfiguration
from dlt.common.typing import TSecretValue


@configspec
class ZendeskCredentialsBase(CredentialsConfiguration):
    """
    The Base version of all the ZendeskCredential classes.
    """

    subdomain: str
    __config_gen_annotations__: ClassVar[list[str]] = []


@configspec
class ZendeskCredentialsEmailPass(ZendeskCredentialsBase):
    """
    This class is used to store credentials for Email + Password Authentication
    """

    email: str = ""
    password: TSecretValue = dlt.secrets.value


@configspec
class ZendeskCredentialsOAuth(ZendeskCredentialsBase):
    """
    This class is used to store credentials for OAuth Token Authentication
    """

    oauth_token: TSecretValue = dlt.secrets.value


@configspec
class ZendeskCredentialsToken(ZendeskCredentialsBase):
    """
    This class is used to store credentials for Token Authentication
    """

    email: str = ""
    token: TSecretValue = dlt.secrets.value


TZendeskCredentials = Union[ZendeskCredentialsEmailPass, ZendeskCredentialsToken, ZendeskCredentialsOAuth]
