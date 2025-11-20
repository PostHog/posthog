#!/usr/bin/env python3
"""
Script to check which classes in posthog/schema.py are actually used in the codebase.
"""

import ast
import re
import subprocess
from pathlib import Path
from collections import defaultdict
from typing import Set, Dict, List

# Paths to search
WORKSPACE_ROOT = Path(__file__).parent
SCHEMA_FILE = WORKSPACE_ROOT / "posthog" / "schema.py"


def extract_classes_from_schema() -> Set[str]:
    """Extract all class names from schema.py"""
    classes = set()
    
    with open(SCHEMA_FILE, "r") as f:
        content = f.read()
    
    # Parse the file
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.add(node.name)
    except SyntaxError as e:
        print(f"Warning: Could not parse schema.py: {e}")
        # Fallback to regex
        for match in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
            classes.add(match.group(1))
    
    return classes


def find_all_schema_imports() -> tuple[Dict[str, Set[str]], Set[str]]:
    """Find all imports from posthog.schema in one pass"""
    # Find all files that import from posthog.schema
    cmd = [
        "grep",
        "-r",
        "--include=*.py",
        "-h",
        "from posthog.schema import",
        str(WORKSPACE_ROOT),
    ]
    
    exclude_dirs = [
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    ]
    
    for exclude in exclude_dirs:
        cmd.extend(["--exclude-dir", exclude])
    
    class_to_files: Dict[str, Set[str]] = defaultdict(set)
    wildcard_files: Set[str] = set()
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if not line.strip():
                    continue
                
                # Check for wildcard import
                if re.search(r"from\s+posthog\.schema\s+import\s+\*", line):
                    # Extract file path from grep output (format: file:content)
                    if ":" in line:
                        file_path = line.split(":", 1)[0].strip()
                        wildcard_files.add(file_path)
                    continue
                
                # Extract class names from import statement
                match = re.search(r"from\s+posthog\.schema\s+import\s+(.+)", line)
                if match:
                    imports_str = match.group(1)
                    # Handle multi-line imports (they'll be on separate lines)
                    # Extract file path if present
                    file_path = None
                    if ":" in line:
                        parts = line.split(":", 1)
                        file_path = parts[0].strip()
                        imports_str = parts[1].strip()
                    
                    # Parse class names (handle parentheses, commas, etc.)
                    # Remove parentheses for multi-line imports
                    imports_str = re.sub(r"\(|\)", "", imports_str)
                    # Split by comma
                    for item in imports_str.split(","):
                        item = item.strip()
                        # Remove any trailing comments or newlines
                        item = re.sub(r"\s*#.*$", "", item)
                        if item and item != "*":
                            if file_path:
                                class_to_files[item].add(file_path)
                            else:
                                class_to_files[item].add("unknown")
        
        # Also check for posthog.schema.ClassName usage
        cmd2 = [
            "grep",
            "-r",
            "--include=*.py",
            "-h",
            "posthog.schema.",
            str(WORKSPACE_ROOT),
        ]
        for exclude in exclude_dirs:
            cmd2.extend(["--exclude-dir", exclude])
        
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
        if result2.returncode == 0:
            for line in result2.stdout.split("\n"):
                if not line.strip():
                    continue
                # Extract class name from posthog.schema.ClassName
                match = re.search(r"posthog\.schema\.(\w+)", line)
                if match:
                    class_name = match.group(1)
                    file_path = line.split(":", 1)[0].strip() if ":" in line else "unknown"
                    class_to_files[class_name].add(file_path)
        
    except subprocess.TimeoutExpired:
        print("Warning: grep timed out")
    except Exception as e:
        print(f"Warning: grep error: {e}")
    
    return class_to_files, wildcard_files


def main():
    print("Extracting classes from schema.py...")
    all_classes = extract_classes_from_schema()
    print(f"Found {len(all_classes)} classes in schema.py\n")
    
    print("Finding all imports from posthog.schema...")
    class_to_files, wildcard_files = find_all_schema_imports()
    
    print(f"Found {len(class_to_files)} classes imported")
    print(f"Found {len(wildcard_files)} files with wildcard imports\n")
    
    used_classes: Set[str] = set()
    class_usage_locations: Dict[str, List[str]] = defaultdict(list)
    
    # Process found imports
    for class_name, files in class_to_files.items():
        used_classes.add(class_name)
        # Convert absolute paths to relative
        for file_path in files:
            if file_path == "unknown":
                continue
            try:
                rel_path = Path(file_path).relative_to(WORKSPACE_ROOT)
                class_usage_locations[class_name].append(str(rel_path))
            except ValueError:
                class_usage_locations[class_name].append(file_path)
    
    unused_classes = all_classes - used_classes
    
    # Print results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    
    print(f"\nTotal classes: {len(all_classes)}")
    print(f"Used classes: {len(used_classes)}")
    print(f"Unused classes: {len(unused_classes)}")
    
    if wildcard_files:
        print(f"\n⚠️  Warning: Found {len(wildcard_files)} files with wildcard imports:")
        for f in wildcard_files[:10]:  # Show first 10
            try:
                rel_path = Path(f).relative_to(WORKSPACE_ROOT)
                print(f"  - {rel_path}")
            except ValueError:
                print(f"  - {f}")
        if len(wildcard_files) > 10:
            print(f"  ... and {len(wildcard_files) - 10} more")
        print("\n  Classes may appear unused but are actually used via wildcard imports.")
    
    if unused_classes:
        print(f"\n{'=' * 80}")
        print("UNUSED CLASSES:")
        print("=" * 80)
        for class_name in sorted(unused_classes):
            print(f"  - {class_name}")
    else:
        print("\n✅ All classes appear to be used!")
    
    # Optionally show usage locations for used classes
    if class_usage_locations:
        print(f"\n{'=' * 80}")
        print("USAGE LOCATIONS (first 5 per class):")
        print("=" * 80)
        for class_name in sorted(class_usage_locations.keys())[:20]:  # Show first 20 classes
            locations = class_usage_locations[class_name]
            print(f"\n{class_name}:")
            for loc in locations[:5]:
                print(f"  - {loc}")
            if len(locations) > 5:
                print(f"  ... and {len(locations) - 5} more files")


if __name__ == "__main__":
    main()

