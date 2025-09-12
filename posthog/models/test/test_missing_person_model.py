from uuid import UUID

from posthog.test.base import BaseTest

from posthog.models.person.missing_person import MissingPerson


class TestMissingPersonModel(BaseTest):
    def test_generates_deterministic_uuid(self):
        assert MissingPerson(1, "test").uuid == UUID("246f7a43-5507-564f-b687-793ee3c2dd79")
        assert MissingPerson(2, "test").uuid == UUID("00ce873a-549c-548e-bbec-cc804a385dd8")
        assert MissingPerson(1, "test2").uuid == UUID("45c17302-ee44-5596-916a-0eba21f4b638")
