#!/usr/bin/env bash
# Reject tracked paths that cannot be checked out on Windows.
#
# Run on Linux CI: Windows runners cannot execute this after checkout because Git
# rejects reserved device names such as aux.hcl while materializing the worktree.
set -euo pipefail
export LC_ALL=C

# core.quotePath=false keeps valid non-ASCII filenames readable. Git still quotes
# control characters, which also makes this check reject them through `\\` or `"`.
status=0
if ! git -c core.quotePath=false ls-files | awk -F/ '
function fail(path, component, reason) {
    printf "::error file=%s::\047%s\047 %s\n", path, component, reason
    bad = 1
}

function is_reserved(component, lower) {
    lower = tolower(component)
    # Git for Windows uses isdigit() after LPT, so its checkout rejects LPT0 too.
    return lower ~ /^(con|prn|aux|nul|conin\$|conout\$|com[1-9]|lpt[0-9]|com¹|com²|com³|lpt¹|lpt²|lpt³) *([.:].*)?$/
}

function is_ntfs_dotgit(component, lower) {
    lower = tolower(component)
    return lower ~ /^git~1[ .]*$/
}

{
    for (i = 1; i <= NF; i++) {
        component = $i

        if (is_reserved(component)) {
            fail($0, component, "uses a Windows-reserved device name")
        }
        if (is_ntfs_dotgit(component)) {
            fail($0, component, "uses the protected NTFS alias for .git")
        }
        if (component ~ /[<>:"\\|?*]/ || component ~ /[[:cntrl:]]/) {
            fail($0, component, "contains characters that Windows filenames do not support")
        }
        if (component ~ /[. ]$/) {
            fail($0, component, "ends with a dot or space, which Windows does not support")
        }
    }

}

END {
    exit bad
}
'; then
    status=1
fi

# NTFS is case-insensitive for non-ASCII names too. Read NUL-delimited paths so
# whitespace and quoting cannot hide a collision from Windows-style casing.
if ! git ls-files -z | PYTHONUTF8=1 python3 -c '
import os
import sys

def windows_fold(value: str) -> str:
    result: list[str] = []
    for character in value:
        upper = character.upper()
        if ord(character) <= 0xFFFF and len(upper) == 1 and ord(upper) <= 0xFFFF:
            result.append(upper)
        else:
            result.append(character)
    return "".join(result)

bad = False
files: dict[str, str] = {}
directories: dict[str, tuple[str, str]] = {}
for raw_path in sys.stdin.buffer.read().split(b"\0"):
    if not raw_path:
        continue
    path = os.fsdecode(raw_path)
    folded = windows_fold(path)
    other = files.get(folded)
    if other is not None and other != path:
        print(f"::error file={path}::\047{path}\047 collides with \047{other}\047 on case-insensitive Windows filesystems")
        bad = True
    else:
        files[folded] = path

    directory = directories.get(folded)
    if directory is not None:
        name, owner = directory
        print(f"::error file={path}::\047{path}\047 is a file, but \047{owner}\047 requires \047{name}\047 to be a directory on case-insensitive Windows filesystems")
        bad = True

    parts = path.split("/")
    for index in range(1, len(parts)):
        name = "/".join(parts[:index])
        folded_name = windows_fold(name)
        other = files.get(folded_name)
        if other is not None:
            print(f"::error file={path}::\047{path}\047 requires \047{name}\047 to be a directory, but it collides with tracked file \047{other}\047 on case-insensitive Windows filesystems")
            bad = True
        directories.setdefault(folded_name, (name, path))

raise SystemExit(bad)
'; then
    status=1
fi

if [ "$status" -eq 0 ]; then
    echo "All tracked paths are Windows-compatible."
fi

exit "$status"
