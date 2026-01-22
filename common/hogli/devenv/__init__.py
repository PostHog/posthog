"""Intent-based developer environment system.

This module provides tools for selecting products/features developers work on
and starting only the minimum required services.

Key components:
- IntentMap: Domain model defining intents, capabilities, and presets
- ProcessRegistry: Abstraction over process definitions (mprocs, pm2, etc.)
- IntentResolver: Resolves intents to the minimal set of processes
- MprocsGenerator: Generates mprocs.yaml configuration
"""

from .generator import MprocsConfig, MprocsGenerator
from .profile import DeveloperProfile, ProfileManager
from .registry import MprocsRegistry, ProcessRegistry, create_mprocs_registry
from .resolver import IntentMap, IntentResolver, load_intent_map
from .wizard import SetupWizard, run_setup_wizard

__all__ = [
    "IntentResolver",
    "IntentMap",
    "load_intent_map",
    "DeveloperProfile",
    "ProfileManager",
    "ProcessRegistry",
    "MprocsRegistry",
    "create_mprocs_registry",
    "MprocsGenerator",
    "MprocsConfig",
    "SetupWizard",
    "run_setup_wizard",
]
