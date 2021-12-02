import pytest


# :TRICKY: Integrate syrupy with unittest test cases
@pytest.fixture
def unittest_snapshot(request, snapshot):
    request.cls.snapshot = snapshot
