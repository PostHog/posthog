from posthog.temporal.common.heartbeat_sync import HeartbeaterSync


def test_current_details_use_the_latest_assigned_tuple() -> None:
    heartbeater = HeartbeaterSync(details=("copy",))
    heartbeater.details = ("add_data_files", {"file_count": 15229})

    assert heartbeater.current_details() == ("add_data_files", {"file_count": 15229})


def test_current_details_prefer_the_provider() -> None:
    heartbeater = HeartbeaterSync(
        details=("stale",), details_provider=lambda: ("add_data_files", {"query_progress": 0.4})
    )

    assert heartbeater.current_details() == ("add_data_files", {"query_progress": 0.4})


def test_current_details_keep_static_details_when_the_provider_fails() -> None:
    def boom() -> tuple[object, ...]:
        raise RuntimeError("progress poll failed")

    heartbeater = HeartbeaterSync(details=("add_data_files",), details_provider=boom)

    assert heartbeater.current_details() == ("add_data_files",)
