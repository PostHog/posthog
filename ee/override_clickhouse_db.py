import os

import pytest


@pytest.hookimpl(hookwrapper=True)
def override_clickhouse_db(worker_id):
    import logging

    logger = logging.getLogger(__name__)
    logger.warn("{}{}".format("hey", "oi"))
    os.environ["CLICKHOUSE_TEST_DB"] = worker_id
