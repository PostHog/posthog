"""Environment loading and validation for the eval harness.

Django-free on purpose: ``__main__`` loads the env file before ``django.setup()``,
so nothing here may touch Django settings or the ORM.
"""

from __future__ import annotations

import os
from collections.abc import Collection
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .providers import PreflightError
from .requirements import SuiteKind

REPO_ROOT = Path(__file__).parents[5]


class CoreEvalEnv(BaseModel):
    """Environment variables every eval run needs, regardless of suite kind.

    Field names are the literal environment variable names; each description is
    surfaced in the preflight error so a missing variable says what it is for.
    Provider-specific prerequisites with non-env fallbacks (Modal tokens vs
    ``~/.modal.toml``, ``NGROK_AUTHTOKEN`` vs the ngrok config file) stay in the
    provider strategies' ``preflight()``.
    """

    model_config = ConfigDict(extra="ignore")

    BRAINTRUST_API_KEY: str = Field(
        min_length=1,
        description="records experiments and scores to Braintrust",
    )


class SandboxEvalEnv(BaseModel):
    """Additional variables sandboxed suites need."""

    model_config = ConfigDict(extra="ignore")

    SANDBOX_JWT_PRIVATE_KEY: str = Field(
        min_length=1,
        description="signs the sandboxed agent's API tokens; the dev key ships in .env.example",
    )
    LLM_GATEWAY_ANTHROPIC_API_KEY: str = Field(
        min_length=1,
        description="Anthropic API key the LLM gateway proxies the agent's model calls with",
    )


class OneShotEvalEnv(BaseModel):
    """Additional variables one-shot suites need."""

    model_config = ConfigDict(extra="ignore")

    LLM_GATEWAY_ANTHROPIC_API_KEY: str = Field(
        min_length=1,
        description="Anthropic API key one-shot generation tasks call the model with directly",
    )


class CodexEvalEnv(BaseModel):
    """Additional variables required when sandboxed suites use the codex runtime."""

    model_config = ConfigDict(extra="ignore")

    LLM_GATEWAY_OPENAI_API_KEY: str = Field(
        min_length=1,
        description="OpenAI API key the LLM gateway proxies the codex agent's model calls with",
    )


ENV_MODELS_BY_KIND: dict[SuiteKind, tuple[type[BaseModel], ...]] = {
    SuiteKind.SANDBOXED: (SandboxEvalEnv,),
    SuiteKind.ONE_SHOT: (OneShotEvalEnv,),
}


def load_env_file() -> None:
    """Load the repo-root ``.env`` into the environment, shell values winning.

    Replaces the manual ``set -a; source .env; set +a`` incantation. Only ``.env``
    is loaded here: hogli already loads ``.env.local`` / ``.env.development`` /
    ``.env.services`` before `hogli evals:sandboxed` reaches this process, and its
    line-based parser cannot represent ``.env``'s quoted multiline PEM keys — so
    this file is the harness's job, via dotenv, which parses them correctly.
    ``override=False`` keeps hogli's precedence: anything already exported (by the
    shell or by hogli's env loading) wins over ``.env``.
    """
    load_dotenv(REPO_ROOT / ".env", override=False)


def validate_eval_env(agent_runtime: str = "claude", *, kinds: Collection[SuiteKind] = (SuiteKind.SANDBOXED,)) -> None:
    """Fail fast, before any infrastructure boots, if a required variable is unset.

    Only the env models for the selected suites' kinds are checked, so a run
    without sandboxed suites doesn't demand sandbox credentials. Without this a
    missing key surfaces minutes into a run as an opaque mid-case failure
    (gateway 401s, Braintrust login errors) instead of a one-line fix.
    """
    models: list[type[BaseModel]] = [CoreEvalEnv]
    for kind, kind_models in ENV_MODELS_BY_KIND.items():
        if kind in kinds:
            models.extend(kind_models)
    if SuiteKind.SANDBOXED in kinds and agent_runtime == "codex":
        models.append(CodexEvalEnv)

    lines = []
    seen: set[str] = set()
    for model in models:
        try:
            model.model_validate(dict(os.environ))
        except ValidationError as e:
            fields = model.model_fields
            for error in e.errors():
                name = str(error["loc"][0]) if error["loc"] else "?"
                if name in seen:
                    continue
                seen.add(name)
                description = fields[name].description if name in fields else ""
                lines.append(f"  - {name}: {description}")
    if lines:
        raise PreflightError(
            "Missing required environment variables:\n"
            + "\n".join(lines)
            + f"\nExport them in your shell, add them to {REPO_ROOT / '.env'} (loaded automatically), "
            "or keep them in .env.local and run via `hogli evals:sandboxed`."
        )
