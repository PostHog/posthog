#!/bin/bash
# djlint runs isolated through `uv tool run` instead of from the project venv, because
# two separate things stop it being a normal dependency:
#
#   * djlint >= 1.40 needs click >= 8.2, and dagster caps click below 8.2. uv resolves
#     that conflict by silently picking djlint 1.39.5, which then dies at runtime on a
#     click 8.2 API it expects to exist.
#   * An older djlint does install, but pathspec then selects its re2 backend (google-re2
#     is a posthog dependency) and djlint cannot pickle that to its worker processes, so
#     any run touching more than one file dies with "cannot pickle 're2._re2.Set' object".
#
# Running the tool isolated sidesteps both and keeps the version pinned in one place.
# Everything else (profile, indent, ignored rules) lives in [tool.djlint] in pyproject.toml.
#
# hogli calls this through `bash`, so it does not depend on the executable bit.

set -uo pipefail

DJLINT_VERSION="1.44.2"

usage() {
    echo "usage: ${0##*/} (--reformat|--check|--lint) [paths...]" >&2
    exit 2
}

[ "$#" -ge 1 ] || usage
mode="$1"
shift

shopt -s nullglob
format_paths=(posthog/templates products/*/backend/templates)
shopt -u nullglob

case "$mode" in
    --reformat | --check) default_paths=("${format_paths[@]}") ;;
    # Linting is scoped to the email templates, the only tree currently clean against the
    # rule set. The rest carry pre-existing findings (hardcoded admin URLs, single-quoted
    # attributes) that want fixing on their own, not as a side effect of a formatting run.
    --lint) default_paths=(posthog/templates/email) ;;
    *) usage ;;
esac

if [ "$#" -gt 0 ]; then
    paths=("$@")
else
    paths=("${default_paths[@]}")
fi

djlint() {
    uv tool run --from "djlint==$DJLINT_VERSION" djlint "${paths[@]}" "$@"
}

if [ "$mode" != "--reformat" ]; then
    djlint "$mode"
    exit $?
fi

# A few templates need a second pass before djlint settles, so one run can leave behind
# files that --check still flags. Reformat until it reports nothing left to change, which
# keeps `format:html` and `format:html:check` in agreement. Exit 1 means "rewrote a file",
# which is success for a formatter; 2 and up are real errors.
for _ in 1 2 3; do
    djlint --reformat
    status=$?
    [ "$status" -le 1 ] || exit "$status"
    [ "$status" -eq 1 ] || break
done

exit 0
