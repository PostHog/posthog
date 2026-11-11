# ruff: noqa: T201
import os
import json
import math
from pathlib import Path

# Approximate marginal compile and test durations, fitted by non-negative least
# squares over shard durations. Fixed setup overhead is excluded from the weights.
PACKAGE_WEIGHTS: dict[str, int] = {
    "affected-services": 37,
    "assignment-coordination": 5,
    "capture": 102,
    "capture-load-gen": 38,
    "common-ingestion-warnings": 59,
    "ingestion-common-alloc": 5,
    "ingestion-common-compression": 5,
    "ingestion-common-continuous-profiling": 9,
    "ingestion-common-database": 35,
    "ingestion-common-kafka": 5,
    "ingestion-common-liveness": 5,
    "ingestion-common-metrics": 5,
    "ingestion-common-redis": 12,
    "ingestion-common-types": 16,
    "ingestion-consumer": 20,
    "ingestion-control-plane": 41,
    "ingestion-health": 5,
    "ingestion-lifecycle": 5,
    "ingestion-limiters": 5,
    "ingestion-serve-metrics": 5,
    "k8s-awareness": 116,
    "kafka-assigner": 175,
    "kafka-assigner-proto": 5,
    "kafka-deduplicator": 129,
    "keyed-stash": 5,
    "personhog-common": 7,
    "personhog-coordination": 230,
    "personhog-identity": 80,
    "personhog-leader": 113,
    "personhog-proto": 9,
    "personhog-replica": 37,
    "personhog-router": 114,
    "personhog-stateright": 173,
    "personhog-test-harness": 33,
    "personhog-writer": 63,
    "pgapi": 40,
    "pgcollector": 45,
    "property-defs-rs": 74,
    "property-vals-rs": 70,
}

DEFAULT_WEIGHT = 60
TARGET_SECONDS = 8 * 60


def plan_shards(affected_crates: set[str]) -> list[list[str]]:
    # An empty affected set means a full build. Affected new crates still receive
    # coverage before their measured weight has been added to the table.
    packages = PACKAGE_WEIGHTS.copy()
    if affected_crates:
        for name in affected_crates - packages.keys():
            packages[name] = DEFAULT_WEIGHT
        packages = {name: weight for name, weight in packages.items() if name in affected_crates}
    shard_count = max(1, math.ceil(sum(packages.values()) / TARGET_SECONDS))
    buckets: list[list[str]] = [[] for _ in range(shard_count)]
    times = [0] * shard_count
    for name in sorted(packages, key=lambda name: -packages[name]):
        lightest = min(range(shard_count), key=lambda index: times[index])
        buckets[lightest].append(name)
        times[lightest] += packages[name]
    return [sorted(bucket) for bucket in buckets if bucket]


def main() -> None:
    affected: set[str] = set(json.loads(os.environ.get("AFFECTED_CRATES", "[]")))
    unknown = affected - PACKAGE_WEIGHTS.keys()
    if unknown:
        print(
            f"WARNING: affected crates missing from weight table (using {DEFAULT_WEIGHT}s default): {', '.join(sorted(unknown))}"
        )
        print("Add them to the packages dict in ingestion/ci/bin/rust_test_shards.py with measured weights.")
    print(
        f"Selective build: testing {len(affected)} of affected crates" if affected else "Full build: testing all crates"
    )
    shards = plan_shards(affected)
    total = 0
    for index, shard in enumerate(shards, start=1):
        seconds = sum(PACKAGE_WEIGHTS.get(name, DEFAULT_WEIGHT) for name in shard)
        total += seconds
        print(f"Shard {index} ({seconds}s): {', '.join(shard)}")
    print(f"\nTotal: {total}s across {len(shards)} shards (target ≤{TARGET_SECONDS}s/shard)")
    matrix = {"include": [{"packages": " ".join(shard)} for shard in shards]}
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"matrix={json.dumps(matrix)}\n")


if __name__ == "__main__":
    main()
