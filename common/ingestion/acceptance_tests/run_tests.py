#!/usr/bin/env python3
"""Main test runner for PostHog acceptance tests."""

import sys
import logging
import subprocess
from pathlib import Path

# Configure logging for the test runner
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def run_tests():
    """Run the acceptance test suite."""
    test_dir = Path(__file__).parent

    # Use virtual environment if it exists
    venv_python = test_dir / ".venv" / "bin" / "python"
    if venv_python.exists():
        python_cmd = str(venv_python)
    else:
        python_cmd = sys.executable

    # Run pytest on all test files
    # -v: verbose
    # -s: no capture, show print statements
    # --tb=short: short traceback format
    # --log-cli-level=DEBUG: show debug logs in console
    # --log-cli-format: format for console logs
    result = subprocess.run(
        [
            python_cmd,
            "-m",
            "pytest",
            "-v",
            "-s",
            "--tb=short",
            "--log-cli-level=DEBUG",
            "--log-cli-format=%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "--log-cli-date-format=%H:%M:%S",
            "--numprocesses=auto",
        ],
        cwd=test_dir,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    return result.returncode


def main():
    """Main entry point for the test runner."""
    logger.info("=" * 60)
    logger.info("PostHog Acceptance Tests")
    logger.info("=" * 60)

    # Log environment info
    import os

    logger.info("Environment:")
    logger.info(
        "  POSTHOG_TEST_BASE_URL: %s", os.environ.get("POSTHOG_TEST_BASE_URL", "http://localhost:8010 (default)")
    )
    logger.info("  POSTHOG_PERSONAL_API_KEY: %s", "SET" if os.environ.get("POSTHOG_PERSONAL_API_KEY") else "NOT SET")

    exit_code = 1

    try:
        # Run the tests
        logger.info("Running acceptance tests...")
        logger.info("-" * 60)
        exit_code = run_tests()
        logger.info("-" * 60)

        if exit_code == 0:
            logger.info("✓ All tests passed!")
        else:
            logger.error("✗ Tests failed with exit code %s", exit_code)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        exit_code = 130
    except Exception as e:
        logger.exception("✗ Error: %s", e)
        exit_code = 1

    logger.info("Done.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
