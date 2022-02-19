#!/usr/bin/env python

import sys

from sentry_sdk import capture_message
from structlog import get_logger

logger = get_logger()


def main():
    message = sys.argv[1]
    logger.error(message)
    capture_message(message)


if __name__ == "__main__":
    main()
