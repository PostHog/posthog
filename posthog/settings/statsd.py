import os

# Metrics - StatsD
STATSD_HOST = os.getenv("STATSD_HOST")
STATSD_PORT = os.getenv("STATSD_PORT", 8125)
STATSD_PREFIX = os.getenv("STATSD_PREFIX", "")
STATSD_TELEGRAF = True
STATSD_CLIENT = "statshog"
STATSD_SEPARATOR = "_"
