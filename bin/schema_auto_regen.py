#!/usr/bin/env python3
"""
Helper script to append auto-regeneration hook to schema.py
"""

import sys
from pathlib import Path

SCHEMA_FILE = Path(__file__).parent.parent / "posthog" / "schema.py"

AUTO_REGEN_CODE = """
# Auto-regeneration hook for missing schema classes
# This is appended by build-schema-python.sh
import subprocess
import sys
from pathlib import Path

_regenerating = False


def __getattr__(name: str):
    \"\"\"
    Catch missing schema classes and auto-regenerate schema.py
    \"\"\"
    global _regenerating
    
    # Avoid infinite recursion
    if _regenerating:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    
    # Check if we're in a test/dev environment (don't auto-regenerate in production)
    import os
    if os.environ.get("DEBUG") == "1":
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    
    # Try to regenerate schema
    try:
        _regenerating = True
        script_path = Path(__file__).parent.parent / "bin" / "build-schema-python.sh"
        
        print(f"⚠️  Schema class '{name}' not found. Regenerating schema...", file=sys.stderr)
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path(__file__).parent.parent,
        )
        
        if result.returncode != 0:
            print(f"❌ Schema regeneration failed:\\n{result.stderr}", file=sys.stderr)
            raise AttributeError(f"module '{__name__}' has no attribute '{name}' (regeneration failed)")
        
        # Reload the module to get the new classes
        import importlib
        module_name = __name__
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
            current_module = sys.modules[module_name]
        else:
            # Fallback: re-import
            current_module = importlib.import_module(module_name)
        
        # Try to get the attribute again
        if hasattr(current_module, name):
            return getattr(current_module, name)
        else:
            raise AttributeError(f"module '{__name__}' has no attribute '{name}' (not found after regeneration)")
    finally:
        _regenerating = False
"""


def append_auto_regen_hook():
    """Append the auto-regeneration hook to schema.py"""
    with open(SCHEMA_FILE, "r") as f:
        lines = f.readlines()
    
    # Find and remove existing hook if present
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if "Auto-regeneration hook for missing schema classes" in line:
            start_idx = i
        if start_idx is not None and i > start_idx and line.strip() and not line.startswith("#") and not line.startswith(" ") and not line.startswith("\t"):
            # Found the end of the hook block
            end_idx = i
            break
    
    if start_idx is not None:
        # Remove existing hook
        if end_idx is None:
            end_idx = len(lines)
        lines = lines[:start_idx] + lines[end_idx:]
    
    # Append the hook
    content = "".join(lines).rstrip() + "\n" + AUTO_REGEN_CODE
    with open(SCHEMA_FILE, "w") as f:
        f.write(content)
    
    print("✅ Added auto-regeneration hook to schema.py")


if __name__ == "__main__":
    append_auto_regen_hook()

