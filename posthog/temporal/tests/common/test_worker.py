import resource

from unittest import mock

from parameterized import parameterized

from posthog.temporal.common import worker


class _FakeRlimit:
    def __init__(self, soft: int, hard: int) -> None:
        self.soft = soft
        self.hard = hard
        self.set_calls: list[tuple[int, int]] = []

    def getrlimit(self, which: int) -> tuple[int, int]:
        assert which == resource.RLIMIT_NOFILE
        return (self.soft, self.hard)

    def setrlimit(self, which: int, limits: tuple[int, int]) -> None:
        assert which == resource.RLIMIT_NOFILE
        # Mirror the kernel: refuse to raise the soft limit above the hard limit.
        if self.hard != resource.RLIM_INFINITY and limits[0] > self.hard:
            raise ValueError("current limit exceeds maximum limit")
        self.set_calls.append(limits)
        self.soft, self.hard = limits


def _run(soft, hard, max_concurrent_activities=50) -> _FakeRlimit:
    fake = _FakeRlimit(soft, hard)
    with (
        mock.patch.object(worker.resource, "getrlimit", fake.getrlimit),
        mock.patch.object(worker.resource, "setrlimit", fake.setrlimit),
    ):
        worker.ensure_file_descriptor_headroom(max_concurrent_activities)
    return fake


class TestEnsureFileDescriptorHeadroom:
    @parameterized.expand(
        [
            # soft limit below the estimated peak is raised to it when the hard limit allows
            ("raises_toward_peak", 1024, 1_048_576, 50, 1024 + 50 * 64),
            # a hard limit below the peak clamps the soft limit to the hard limit, never above it
            ("clamped_to_hard", 1024, 2048, 50, 2048),
        ]
    )
    def test_raises_soft_limit(self, _name, soft, hard, activities, expected_soft):
        fake = _run(soft, hard, activities)
        assert fake.soft == expected_soft
        assert fake.set_calls[-1] == (expected_soft, hard)

    def test_leaves_sufficient_soft_limit_untouched(self):
        needed = worker.BASE_FILE_DESCRIPTORS + 50 * worker.FILE_DESCRIPTORS_PER_ACTIVITY
        fake = _run(soft=needed + 1, hard=1_048_576, max_concurrent_activities=50)
        assert fake.set_calls == []

    def test_infinite_soft_limit_untouched(self):
        fake = _run(soft=resource.RLIM_INFINITY, hard=resource.RLIM_INFINITY)
        assert fake.set_calls == []
