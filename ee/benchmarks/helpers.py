# from functools import lru_cache, wraps
# from os.path import dirname
# import sys
# import os
# import inspect

# os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
# sys.path.append(dirname(dirname(dirname(__file__))))

# import django
# django.setup()

# from ee.clickhouse import client
# from posthog.models.utils import UUIDT

# get_column = lambda rows, index: [row[index] for row in rows]


# def run_query(fn):
#     uuid = str(UUIDT())
#     client._request_information = {"kind": "benchmark", "id": f"{uuid}::${fn.__name__}"}
#     try:
#         fn()
#         return get_clickhouse_query_stats(uuid)
#     finally:
#         client._request_information = None

# def get_clickhouse_query_stats(uuid):
#     client.sync_execute("SYSTEM FLUSH LOGS")
#     rows = client.sync_execute(
#         f"""
#         SELECT
#             query_duration_ms,
#             read_rows,
#             read_bytes,
#             memory_usage
#         FROM system.query_log
#         WHERE
#             query NOT LIKE '%%query_log%%'
#             AND query LIKE %(matcher)s
#             AND type = 'QueryFinish'
#         """,
#         {
#             "matcher": f"%benchmark:{uuid}%"
#         }
#     )

#     return {
#         "query_count": len(rows),
#         "ch_query_time": sum(get_column(rows, 0)),
#         "read_rows": sum(get_column(rows, 1)),
#         "read_bytes": sum(get_column(rows, 2)),
#         "memory_usage": sum(get_column(rows, 3)),
#     }


# class ClickhouseQueryTimer:
#     def __init__(self, func):
#         self.func = func
#         self.samples = []

#     def timeit(self, repeats):
#         samples = []
#         for _ in range(repeats):
#             samples.append(run_query(self.func))
#         self.samples.extend(samples)
#         return sum(s["ch_query_time"] for s in samples)

#     @classmethod
#     def get_timer(self, *param):
#         if param:
#             func = lambda: self.func(*param)
#         else:
#             func = self.func
#         return ClickhouseQueryTimer(func)

# def benchmark_clickhouse(fn):
#     @lru_cache()
#     def run_queries_cached():
#         print('recalculating!!')
#         return [run_query(fn) for _ in range(3)]

#     def get_samples(key):
#         return { 'samples': [s[key] for s in run_queries_cached()], 'number': 1 }

#     new_functions = {
#         f"track_{fn.__name__}_ch_query_time": lambda: get_samples("ch_query_time"),
#         # f"track_{fn.__name__}_read_rows": lambda: get_samples("read_rows"),
#         # f"track_{fn.__name__}_memory_usage": lambda: get_samples("memory_usage"),
#     }

#     frame_locals: Any = inspect.currentframe().f_back.f_locals  # type: ignore
#     for key, benchmark_fn in new_functions.items():
#         benchmark_fn = wraps(fn)(benchmark_fn)
#         benchmark_fn.__name__ = key
#         frame_locals[key] = benchmark_fn
