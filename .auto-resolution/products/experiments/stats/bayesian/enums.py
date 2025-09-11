"""
Enumeration types for the Bayesian stats module.
"""

from enum import Enum


class PriorType(Enum):
    """Types of prior distributions for effect sizes."""

    RELATIVE = "relative"
    ABSOLUTE = "absolute"
