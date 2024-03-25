"""
This module handles how credentials are read in dlt sources
"""
from typing import ClassVar, List, Union
from dlt.common.configuration import configspec
from dlt.common.configuration.specs import CredentialsConfiguration
from dlt.common.typing import TSecretValue


@configspec
class ZendeskCredentialsBase(CredentialsConfiguration):
    """
    The Base version of all the ZendeskCredential classes.
    """

    subdomain: str
    __config_gen_annotations__: ClassVar[List[str]] = []


@configspec
class ZendeskCredentialsEmailPass(ZendeskCredentialsBase):
    """
    This class is used to store credentials for Email + Password Authentication
    """

    email: str
    password: TSecretValue


@configspec
class ZendeskCredentialsOAuth(ZendeskCredentialsBase):
    """
    This class is used to store credentials for OAuth Token Authentication
    """

    oauth_token: TSecretValue


@configspec
class ZendeskCredentialsToken(ZendeskCredentialsBase):
    """
    This class is used to store credentials for Token Authentication
    """

    email: str
    token: TSecretValue


TZendeskCredentials = Union[ZendeskCredentialsEmailPass, ZendeskCredentialsToken, ZendeskCredentialsOAuth]
