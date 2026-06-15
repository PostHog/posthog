"""Shared building blocks for sandboxed-eval seeder hooks.

Seeders are plain callables that receive the per-case
``CustomPromptSandboxContext`` and return a dict that gets merged into the
task output under ``seed`` so scorers can read seeded entity IDs. The
wiring lives in ``ee/hogai/eval/sandboxed/base.py:task()``; the per-entity
seeders live in sibling modules (``insight.py`` etc.).

This module collects pieces every seeder is likely to want:

* ``LOOKUP_PREFIX`` — distinctive substring that should never appear in
  noise names so prompts can name the lookup entity unambiguously.
* ``DEFAULT_NAME_SEED`` — fixed mimesis seed for reproducible noise.
* ``make_name_providers`` — factory that returns a ``(rnd, text, person)``
  bundle with the same seed, so each seeder gets a consistent provider
  set without re-importing mimesis everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import mimesis
import mimesis.random

__all__ = [
    "LOOKUP_PREFIX",
    "DEFAULT_NAME_SEED",
    "NameProviders",
    "make_name_providers",
]


LOOKUP_PREFIX = "[lookup]"
DEFAULT_NAME_SEED = 42


@dataclass(frozen=True)
class NameProviders:
    """Bundle of mimesis providers used to compose noise entity names.

    Frozen so it can be passed around without callers worrying about
    mutating shared state, even though mimesis providers are themselves
    stateful generators.
    """

    rnd: mimesis.random.Random
    text: mimesis.Text
    person: mimesis.Person


def make_name_providers(seed: int = DEFAULT_NAME_SEED) -> NameProviders:
    """Build a fresh, deterministically-seeded mimesis provider bundle."""
    return NameProviders(
        rnd=mimesis.random.Random(seed),
        text=mimesis.Text(seed=seed),
        person=mimesis.Person(seed=seed),
    )
