"""Command-line entry point for running acceptance tests.

Usage:
    python -m common.ingestion.acceptance_tests_v2
    python -m common.ingestion.acceptance_tests_v2 --output results.json
    python -m common.ingestion.acceptance_tests_v2 --filter test_capture
"""

import sys
import json
import logging
import argparse

from .runner import run_tests

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ingestion acceptance tests")
    parser.add_argument(
        "--output",
        "-o",
        help="Path to write JSON results file",
    )
    parser.add_argument(
        "--filter",
        "-k",
        help="Only run tests containing this substring in their name",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only print summary, not full report",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    test_filter = None
    if args.filter:
        filter_str = args.filter

        def test_filter(t):
            return filter_str in t.name or filter_str in t.full_name

    result = run_tests(test_filter=test_filter)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        logger.info("Results written to %s", args.output)

    if args.quiet:
        status = "PASSED" if result.success else "FAILED"
        logger.info("%s: %d/%d tests passed", status, result.passed_count, result.total_count)
    else:
        logger.info(result.format_report())

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
