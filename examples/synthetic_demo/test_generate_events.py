"""Sanity checks for the synthetic demo generator (DEMO ONLY)."""

from generate_events import EVENTS, generate


def test_generate_is_deterministic():
    assert [e.distinct_id for e in generate(10)] == [e.distinct_id for e in generate(10)]


def test_generate_count():
    assert len(generate(25)) == 25


def test_events_are_known():
    for e in generate(50):
        assert e.event in EVENTS
        assert e.properties["is_demo"] is True
