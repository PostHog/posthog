#!/usr/bin/env bash
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prepare-product-junit-for-trunk.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

create_product() {
    local root="$1" directory="$2" package_name="$3" report="$4"
    mkdir -p "$root/products/$directory"
    printf '{"name":"%s"}\n' "$package_name" >"$root/products/$directory/package.json"
    if [ -n "$report" ]; then
        printf '%s\n' "$report" >"$root/products/$directory/junit-product.xml"
    fi
}

run_case() {
    local name="$1" filters="$2" expected_status="$3" warehouse_report="$4" other_report="$5"
    local excluded_paths="${6:-products/warehouse_sources/junit-product.xml}"
    local root="$workdir/$name" output status excluded_path product
    read -r -a exclusions <<<"$excluded_paths"
    mkdir -p "$root"
    create_product "$root" warehouse_sources @posthog/products-warehouse-sources "$warehouse_report"
    create_product "$root" warehouse_sources_queue @posthog/products-warehouse-sources-queue '<testsuite tests="1" failures="0" />'
    create_product "$root" other @posthog/products-other "$other_report"

    set +e
    output=$(cd "$root" && bash "$script" trunk-junit "$filters" "${exclusions[@]}" 2>&1)
    status=$?
    set -e

    if [ "$status" -ne "$expected_status" ]; then
        echo "FAIL: $name returned $status, expected $expected_status"
        printf '%s\n' "$output"
        exit 1
    fi
    for excluded_path in "${exclusions[@]}"; do
        product="$(basename "$(dirname "$excluded_path")")"
        if [ -e "$root/trunk-junit/junit-product-$product.xml" ]; then
            echo "FAIL: $name staged excluded report $excluded_path"
            exit 1
        fi
    done
    if [ ! -e "$root/trunk-junit/junit-product-warehouse_sources_queue.xml" ]; then
        echo "FAIL: $name did not stage an included report"
        exit 1
    fi
    echo "ok: $name"
}

run_case exact-package-match '--filter=@posthog/products-warehouse-sources-queue' 0 '' '<testsuite tests="1" failures="0" />'
run_case selected-report-missing '--filter=@posthog/products-warehouse-sources' 1 '' '<testsuite tests="1" failures="0" />'
run_case selected-report-passes '--filter=@posthog/products-warehouse-sources' 0 '<testsuite tests="1" failures="0" />' '<testsuite tests="1" failures="0" />'
run_case selected-report-fails '--filter=@posthog/products-warehouse-sources' 1 '<testsuite tests="1" failures="1"><testcase><failure /></testcase></testsuite>' '<testsuite tests="1" failures="0" />'
run_case multiple-exclusions '--filter=@posthog/products-other' 0 '<testsuite tests="1" failures="0" />' '<testsuite tests="1" failures="0" />' 'products/warehouse_sources/junit-product.xml products/other/junit-product.xml'

echo "Product JUnit preparation regression cases passed."
