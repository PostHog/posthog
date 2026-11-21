from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_modeling.backend.facade.testing import PATCH_HELPERS


class TestFacadeTestingPatches(SimpleTestCase):
    @parameterized.expand([(helper.__name__, helper) for helper in PATCH_HELPERS])
    def test_patch_target_exists(self, _name, helper) -> None:
        patcher = helper()
        patcher.start()
        patcher.stop()
