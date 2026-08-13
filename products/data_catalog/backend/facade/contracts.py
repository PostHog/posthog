"""
Contract types for data_catalog.

Frozen dataclasses that define what this product exposes to other products. No Django imports.
"""

from posthog.dataclasses import frozen


@frozen
class ApprovedMetricSummary:
    """An approved, non-drifted metric as a caller outside this product may see it.

    Carries no definition: the per-metric denied-table filtering the information_schema loader
    applies has nothing to hide in a name/label/description.
    """

    name: str
    display_name: str
    description: str
