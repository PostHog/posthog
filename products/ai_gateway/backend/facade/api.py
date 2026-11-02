"""
Facade for ai_gateway.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from posthog.models.user import User

from .. import logic
from . import contracts
from .enums import DevTokenClient


def eligibility_refusal(user: User) -> contracts.DevTokenRefused | None:
    return logic.eligibility_refusal(user)


def mint_dev_token(user: User, client: DevTokenClient) -> contracts.MintedDevToken:
    return logic.mint(user, client)


def dev_token_usage(user: User) -> contracts.DevTokenUsage:
    return logic.usage(user)


def dev_team_usage(user: User) -> contracts.DevTeamUsage:
    return logic.team_usage(user)


def dev_token_status(token: str) -> contracts.DevToken:
    return logic.token_status(token)


def revoke_dev_tokens(user: User, token_id: str | None) -> int:
    return logic.revoke(user, token_id)


def authorize_cli(user: User, code_challenge: str) -> str:
    return logic.authorize_cli(user, code_challenge)


def exchange_cli_code(code: str, code_verifier: str) -> contracts.MintedDevToken:
    return logic.exchange_cli_code(code, code_verifier)
