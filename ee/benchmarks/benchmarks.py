from ee.clickhouse.client import sync_execute

from .helpers import *


@benchmark_clickhouse
def track_foobar():
    sync_execute("SELECT sleep(1)")
