"""Intent-based developer environment system.

This module provides tools for selecting products/features developers work on
and starting only the minimum required services.

Key components:
- IntentMap: Domain model defining intents and capabilities
- ProcessRegistry: Abstraction over process definitions (mprocs, pm2, etc.)
- IntentResolver: Resolves intents to the minimal set of processes
- MprocsGenerator: Generates mprocs.yaml configuration
"""

from .generator import (
    DevenvConfig,
    MprocsConfig,
    MprocsGenerator,
    build_docker_compose_command,
    build_vscode_compounds,
    get_generated_mprocs_path,
    get_vscode_launch_path,
    load_devenv_config,
    regenerate_vscode_launch_config,
)
from .registry import MprocsRegistry, ProcessRegistry, create_mprocs_registry
from .resolver import IntentMap, IntentResolver, load_intent_map
from .wizard import run_setup_wizard

__all__ = [
    "IntentResolver",
    "IntentMap",
    "load_intent_map",
    "DevenvConfig",
    "load_devenv_config",
    "get_generated_mprocs_path",
    "build_docker_compose_command",
    "build_vscode_compounds",
    "ProcessRegistry",
    "MprocsRegistry",
    "create_mprocs_registry",
    "MprocsGenerator",
    "MprocsConfig",
    "get_vscode_launch_path",
    "regenerate_vscode_launch_config",
    "run_setup_wizard",
]
