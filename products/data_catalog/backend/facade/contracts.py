"""
Contract types for data_catalog.

Frozen dataclasses that define what this product exposes to other products. No Django imports.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class GovernedMetricSummary:
    """One approved, non-drifted metric, shaped for injection into agent prompts.

    Carries only the fields an agent needs to recognize a governed measure and run it by name
    via `data-catalog-metric-run`; the definition itself stays behind the run path so a prompt
    can never present an unexecuted query as the canonical number.
    """

    name: str
    display_name: str
    description: str
    unit: str
