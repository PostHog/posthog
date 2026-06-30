import pytest


@pytest.fixture(autouse=True)
def _activate_personhog_fake():
    """No-op override of the repo-root autouse fixture for the script tests.

    The repo-root ``conftest.py`` registers an autouse ``_activate_personhog_fake``
    that imports ``posthog`` -> ``django``. The ``.github/scripts`` unit tests run
    under a deliberately minimal environment with only ``pytest`` installed and no
    ``django`` (see ``.github/workflows/ci-scripts.yml``), and they never read
    person/group data, so the personhog fake is unnecessary here. Shadowing the
    fixture by name keeps these tests runnable without django.
    """
    yield
