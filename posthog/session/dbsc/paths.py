"""Kept free of imports, because the core middlewares that must let these endpoints through load at startup."""

START_PATH = "/dbsc/start"
REFRESH_PATH = "/dbsc/refresh"
ENDPOINT_PATHS = frozenset({START_PATH, REFRESH_PATH})
