import sys
from typing import Literal, NotRequired, TypedDict

def load_core_filter_definitions(filename):
    """Executes the file and returns the CORE_FILTER_DEFINITIONS_BY_GROUP constant."""
    with open(filename, 'r') as f:
        code = f.read()
    local_vars = {}
    extra_globals = {"NotRequired": NotRequired, "Literal": Literal, "TypedDict": TypedDict}
    exec(code, extra_globals, local_vars)
    return local_vars['CORE_FILTER_DEFINITIONS_BY_GROUP']

def deep_compare(a, b, path=""):
    differences = []
    if type(a) != type(b):
        differences.append(f"Type mismatch at {path or 'root'}: {type(a)} vs {type(b)}")
        return differences

    if isinstance(a, dict):
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        for key in a_keys - b_keys:
            differences.append(f"Key '{path + '.' if path else ''}{key}' found in first file but missing in second")
        for key in b_keys - a_keys:
            differences.append(f"Key '{path + '.' if path else ''}{key}' found in second file but missing in first")
        for key in a_keys & b_keys:
            differences.extend(deep_compare(a[key], b[key], f"{path + '.' if path else ''}{key}"))
    elif isinstance(a, list):
        if len(a) != len(b):
            differences.append(f"List length mismatch at {path or 'root'}: {len(a)} vs {len(b)}")
        for index, (item_a, item_b) in enumerate(zip(a, b)):
            differences.extend(deep_compare(item_a, item_b, f"{path}[{index}]"))
    else:
        if a != b:
            differences.append(f"Value mismatch at {path or 'root'}: {a} vs {b}")
    return differences

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python compare.py file1.py file2.py")
        sys.exit(1)

    file1, file2 = sys.argv[1], sys.argv[2]
    defs1 = load_core_filter_definitions(file1)
    defs2 = load_core_filter_definitions(file2)

    diffs = deep_compare(defs1, defs2)

    if diffs:
        print("Differences found:")
        for diff in diffs:
            print(" -", diff)
    else:
        print("No differences found.")
