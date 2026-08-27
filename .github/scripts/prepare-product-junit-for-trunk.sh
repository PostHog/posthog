#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "usage: $0 OUTPUT_DIR MATRIX_FILTERS EXCLUDED_JUNIT_PATH..." >&2
    exit 2
fi

output_dir="$1"
matrix_filters="$2"
shift 2
excluded_reports=("$@")
read -r -a selected_filters <<<"$matrix_filters"

is_excluded() {
    local report="$1" excluded_report
    for excluded_report in "${excluded_reports[@]}"; do
        if [ "$report" = "$excluded_report" ]; then
            return 0
        fi
    done
    return 1
}

is_selected() {
    local package_name="$1" filter
    for filter in "${selected_filters[@]}"; do
        if [ "$filter" = "--filter=$package_name" ]; then
            return 0
        fi
    done
    return 1
}

mkdir -p "$output_dir"
find "$output_dir" -maxdepth 1 -type f -name 'junit-product-*.xml' -delete

for report in products/*/junit-product.xml; do
    [ -f "$report" ] || continue
    if ! is_excluded "$report"; then
        product="$(basename "$(dirname "$report")")"
        cp "$report" "$output_dir/junit-product-$product.xml"
    fi
done

excluded_failure=0
for report in "${excluded_reports[@]}"; do
    package_json="$(dirname "$report")/package.json"
    if [ ! -f "$package_json" ]; then
        echo "::error file=$package_json::Cannot resolve the package for excluded JUnit report $report"
        excluded_failure=1
        continue
    fi

    package_name="$(node -e 'process.stdout.write(JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).name)' "$package_json")"
    if ! is_selected "$package_name"; then
        continue
    fi
    if [ ! -f "$report" ]; then
        echo "::error file=$report::The selected package $package_name did not produce its excluded JUnit report"
        excluded_failure=1
    elif grep -qE '<(failure|error)([[:space:]>])' "$report"; then
        echo "::error file=$report::Tests in $package_name failed and cannot use Trunk quarantine"
        excluded_failure=1
    fi
done

exit "$excluded_failure"
