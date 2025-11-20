#!/usr/bin/env python3
"""
Script to remove unused classes from posthog/schema.py.
Run this after building the schema to clean up unused classes.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path
from collections import defaultdict
from typing import Set, Dict, List

# Paths to search
WORKSPACE_ROOT = Path(__file__).parent.parent
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
        print(f"Error: Could not parse schema.py: {e}", file=sys.stderr)
        sys.exit(1)
    
    return classes


def find_internal_class_usage() -> Set[str]:
    """Find all classes that are used internally within schema.py itself"""
    with open(SCHEMA_FILE, "r") as f:
        content = f.read()
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"Error: Could not parse schema.py: {e}", file=sys.stderr)
        sys.exit(1)
    
    all_classes = extract_classes_from_schema()
    used_internally: Set[str] = set()
    
    def extract_class_names_from_annotation(node: ast.AST) -> Set[str]:
        """Extract class names from a type annotation node"""
        found = set()
        
        if isinstance(node, ast.Name):
            # Direct class name reference
            if node.id in all_classes:
                found.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # String literal forward reference: "ClassName"
            if node.value in all_classes:
                found.add(node.value)
        elif isinstance(node, ast.Subscript):
            # Handle generic types like Optional[Class], List[Class], Union[Class1, Class2], dict[str, Class]
            # Check the slice (the part inside brackets)
            if isinstance(node.slice, ast.Tuple):
                # Union[Class1, Class2, ...] or tuple[Class1, Class2]
                for elt in node.slice.elts:
                    found.update(extract_class_names_from_annotation(elt))
            elif node.slice:
                # Optional[Class], List[Class], dict[str, Class], etc.
                found.update(extract_class_names_from_annotation(node.slice))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            # Handle | operator for unions (Python 3.10+): Class1 | Class2
            found.update(extract_class_names_from_annotation(node.left))
            found.update(extract_class_names_from_annotation(node.right))
        elif isinstance(node, ast.Index):
            # Python < 3.9 compatibility
            found.update(extract_class_names_from_annotation(node.value))
        
        return found
    
    # Visit all class definitions and check their field annotations
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check base classes (inheritance)
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id in all_classes:
                    used_internally.add(base.id)
                elif isinstance(base, ast.Subscript):
                    # Handle generic base classes like BaseModel[Type]
                    used_internally.update(extract_class_names_from_annotation(base))
            
            # Check all annotated assignments (field definitions)
            for item in node.body:
                if isinstance(item, ast.AnnAssign):
                    # Type annotations in field definitions: field: Type
                    if item.annotation:
                        used_internally.update(extract_class_names_from_annotation(item.annotation))
                elif isinstance(item, ast.FunctionDef):
                    # Check function return type annotations
                    if item.returns:
                        used_internally.update(extract_class_names_from_annotation(item.returns))
                    # Check function parameter annotations
                    for arg in item.args.args:
                        if arg.annotation:
                            used_internally.update(extract_class_names_from_annotation(arg.annotation))
    
    return used_internally


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
        print("Error: grep timed out", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: grep error: {e}", file=sys.stderr)
        sys.exit(1)
    
    return class_to_files, wildcard_files


def remove_unused_classes(unused_classes: Set[str]) -> int:
    """Remove unused classes from schema.py. Returns number of classes removed."""
    if not unused_classes:
        return 0
    
    with open(SCHEMA_FILE, "r") as f:
        content = f.read()
        lines = content.split("\n")
    
    # Parse the file to find class definitions
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"Error: Could not parse schema.py: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Find all class nodes and their line ranges
    class_ranges: Dict[str, tuple[int, int]] = {}
    
    # Get all top-level class definitions
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in unused_classes:
            # Get the start line (accounting for decorators)
            if node.decorator_list:
                start_line = node.decorator_list[0].lineno - 1  # Start from first decorator
            else:
                start_line = node.lineno - 1  # Convert to 0-based index
            
            # Find the end line by looking at the next top-level node
            end_line = len(lines) - 1
            for next_node in tree.body:
                if next_node.lineno > node.lineno:
                    # Find the line before the next node starts
                    if isinstance(next_node, ast.ClassDef) and next_node.decorator_list:
                        end_line = next_node.decorator_list[0].lineno - 2
                    else:
                        end_line = next_node.lineno - 2
                    break
            
            class_ranges[node.name] = (start_line, end_line)
    
    # Sort by line number (descending) so we can remove from bottom to top
    sorted_ranges = sorted(class_ranges.items(), key=lambda x: x[1][0], reverse=True)
    
    # Remove classes from bottom to top to preserve line numbers
    removed_count = 0
    for class_name, (start, end) in sorted_ranges:
        # Remove the class (inclusive range)
        del lines[start:end + 1]
        removed_count += 1
    
    # Write back to file
    with open(SCHEMA_FILE, "w") as f:
        f.write("\n".join(lines))
        if not lines or lines[-1]:
            f.write("\n")
    
    return removed_count


def main():
    print("Extracting classes from schema.py...")
    all_classes = extract_classes_from_schema()
    print(f"Found {len(all_classes)} classes in schema.py")
    
    print("Finding all imports from posthog.schema...")
    class_to_files, wildcard_files = find_all_schema_imports()
    
    print(f"Found {len(class_to_files)} classes imported externally")
    
    print("Finding classes used internally within schema.py...")
    used_internally = find_internal_class_usage()
    print(f"Found {len(used_internally)} classes used internally")
    
    if wildcard_files:
        print(f"⚠️  Warning: Found {len(wildcard_files)} files with wildcard imports")
        print("  Skipping removal - wildcard imports detected")
        return 0
    
    # A class is used if it's imported externally OR used internally
    used_classes: Set[str] = set(class_to_files.keys()) | used_internally
    unused_classes = all_classes - used_classes
    
    if not unused_classes:
        print("\n✅ All classes are used - nothing to remove!")
        return 0
    
    print(f"\nFound {len(unused_classes)} unused classes")
    print("Removing unused classes from schema.py...")
    
    removed_count = remove_unused_classes(unused_classes)
    
    print(f"✅ Removed {removed_count} unused classes from schema.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

