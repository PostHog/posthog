from products.batch_exports.backend.temporal.destinations.workflows_batch_export import Tracking, TrackingAddSet


def test_tracking_increase_increments_count():
    t = Tracking()

    assert t.count == 0
    t.increment()
    assert t.count == 1


def test_tracking_add_set_tracks_times_added():
    s = TrackingAddSet()

    class Element:
        pass

    element = Element()

    s.add(element)
    assert element.__tracking__.count == 1  # type: ignore

    s.remove(element)
    assert element.__tracking__.count == 1  # type: ignore

    s.add(element)
    assert element.__tracking__.count == 2  # type: ignore
