#!/usr/bin/env bash
set -euo pipefail

checker=.github/scripts/check-windows-paths.sh
index="$(mktemp)"
trap 'rm -f "$index"' EXIT
rm -f "$index"

blob="$(git rev-parse HEAD:.gitignore)"
add_path() {
    GIT_INDEX_FILE="$index" git -c core.protectNTFS=false update-index --add --cacheinfo "100644,$blob,$1"
}

add_path safe/local-aux.hcl
add_path safe/auxiliary.sql
add_path safe/com0.txt
add_path safe/naïve.txt
add_path safe/Straße.ts
add_path safe/Strasse.ts
add_path safe/mydocu~1.txt
add_path safe/𐐨.ts
add_path safe/𐐀.ts
add_path safe/Shared/one.ts
add_path safe/shared/two.ts
add_path 'bad/AUX .txt'
add_path 'bad/CONIN$.log'
add_path 'bad/CONOUT$'
add_path bad/LPT0.txt
add_path bad/COM¹.txt
add_path bad/GIT~1
add_path bad/git~1...
add_path 'bad/name?.txt'
add_path bad/trailing.
add_path case/Foo.ts
add_path case/foo.ts
add_path case/Ä.ts
add_path case/ä.ts
add_path case/Foo
add_path case/foo/bar.txt
add_path reverse/Dir/child.txt
add_path reverse/dir

set +e
output="$(GIT_INDEX_FILE="$index" "$checker")"
status=$?
set -e

if [ "$status" -ne 1 ]; then
    echo "expected checker to reject invalid paths, got exit $status"
    exit 1
fi

for path in 'bad/AUX .txt' 'bad/CONIN$.log' 'bad/CONOUT$' bad/LPT0.txt bad/COM¹.txt bad/GIT~1 bad/git~1... 'bad/name?.txt' bad/trailing. case/foo.ts case/ä.ts case/foo/bar.txt reverse/dir; do
    if ! grep -Fq "file=$path::" <<<"$output"; then
        echo "expected checker error for $path"
        exit 1
    fi
done

if ! grep -Fq "file=bad/git~1...::'git~1...' uses the protected NTFS alias for .git" <<<"$output"; then
    echo "expected checker to recognize the padded git~1 alias"
    exit 1
fi

if grep -Fq 'file=safe/' <<<"$output"; then
    echo "checker rejected a valid path"
    exit 1
fi

echo "Windows path checker regression cases passed."
