#!/usr/bin/env bash
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/trunk-codeowners.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# The generator itself is covered by tools/owners/tests/test_owners.py. These cases stub the
# interpreter so the script's own contract is deterministic on a runner with no Python.
stub_interpreter() {
    local name="$1" exit_code="$2" body="$3"
    cat >"$stub_dir/$name" <<EOF
#!/usr/bin/env bash
target=""
while [ \$# -gt 0 ]; do
    if [ "\$1" = "--codeowners" ]; then target="\$2"; fi
    shift
done
if [ -n "\$target" ] && [ -n "$body" ]; then printf '%s\n' "$body" >"\$target"; fi
exit $exit_code
EOF
    chmod +x "$stub_dir/$name"
}

# A report whose testcases carry the file attribute, which is what Trunk matches against.
# Two cases, because the attribute's position varies by reporter: pytest writes it after classname
# and name, and a reporter that writes it first must match too.
attributable_report='<testsuite><testcase name="t" file="a/b.test.ts" /><testcase file="c/d.test.ts" name="u" /></testsuite>'
# What cargo-nextest, playwright and vitest write: the path lands in classname, which Trunk ignores.
unattributable_report='<testsuite><testcase name="t" classname="a/b.test.ts" profile="x" /></testsuite>'

run_case() {
    local name="$1" uv_exit="$2" uv_body="$3" python_exit="$4" python_body="$5" expect_env="$6" report="${7:-$attributable_report}"
    stub_dir="$workdir/$name-bin"
    mkdir -p "$stub_dir"
    stub_interpreter uv "$uv_exit" "$uv_body"
    stub_interpreter python3 "$python_exit" "$python_body"

    local out_dir="$workdir/$name-out"
    local env_file="$workdir/$name-env"
    local junit="$workdir/$name-junit.xml"
    : >"$env_file"
    printf '%s\n' "$report" >"$junit"

    set +e
    PATH="$stub_dir:$PATH" GITHUB_ENV="$env_file" bash "$script" "$out_dir" "$junit" >"$workdir/$name.log" 2>&1
    local status=$?
    set -e

    if [ "$status" -ne 0 ]; then
        echo "FAIL: $name exited $status, expected 0"
        cat "$workdir/$name.log"
        exit 1
    fi
    if [ "$expect_env" = "yes" ]; then
        if ! grep -qx "TRUNK_CODEOWNERS_PATH=$out_dir" "$env_file"; then
            echo "FAIL: $name did not export TRUNK_CODEOWNERS_PATH"
            exit 1
        fi
        if ! grep -qx "TRUNK_CODEOWNERS_TYPE=github" "$env_file"; then
            echo "FAIL: $name did not pin the CODEOWNERS parser"
            exit 1
        fi
        if [ ! -s "$out_dir/CODEOWNERS" ]; then
            echo "FAIL: $name did not write \$out_dir/CODEOWNERS"
            exit 1
        fi
    elif [ -s "$env_file" ]; then
        echo "FAIL: $name exported an ownership map it should have fallen back from"
        cat "$env_file"
        exit 1
    fi
    echo "ok: $name"
}

run_case generates-with-uv 0 '/a/ @PostHog/team-a' 1 '' yes
run_case falls-back-to-python3 1 '' 0 '/a/ @PostHog/team-a' yes
run_case falls-back-when-both-fail 1 '' 1 '' no
run_case falls-back-on-a-map-with-no-rules 0 '# only a header' 1 '' no
run_case skips-a-report-with-no-file-attribute 0 '/a/ @PostHog/team-a' 1 '' no "$unattributable_report"

env_file="$workdir/no-args-env"
: >"$env_file"
GITHUB_ENV="$env_file" bash "$script" >/dev/null 2>&1
if [ -s "$env_file" ]; then
    echo "FAIL: no-args exported an ownership map"
    exit 1
fi
echo "ok: no-args"

echo "Trunk ownership map regression cases passed."
