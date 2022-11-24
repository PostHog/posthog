from typing import Union

from statshog.client.base import Tags
from statshog.defaults.django import statsd


def timing(metric_name: str, ms: float, tags: Tags = None):
    statsd.timing(metric_name, ms, tags=tags)


def gauge(metric_name: str, value: Union[int, float], tags: Tags = None):
    statsd.gauge(metric_name, value, tags=tags)


def incr(metric_name: str, count: int = 1, tags: Tags = None):
    statsd.incr(metric_name, count, tags=tags)
