"""Intent-based developer environment system.

This module provides tools for selecting products/features developers work on
and starting only the minimum required services.

Key principle: Intent → Capabilities → Units
- Intent: What the developer is working on (products like error_tracking, session_replay)
- Capabilities: Stable abstractions (event_ingestion, replay_storage, analytics_store)
- Units: Actual mprocs processes to run (capture, cymbal, backend)
"""

from .generator import MprocsConfig, MprocsGenerator, create_generator
from .profile import DeveloperProfile, ProfileManager
from .resolver import IntentMap, IntentResolver, load_intent_map
from .wizard import SetupWizard, run_setup_wizard

__all__ = [
    "IntentResolver",
    "IntentMap",
    "load_intent_map",
    "DeveloperProfile",
    "ProfileManager",
    "MprocsGenerator",
    "MprocsConfig",
    "create_generator",
    "SetupWizard",
    "run_setup_wizard",
]
