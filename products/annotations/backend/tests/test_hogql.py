from posthog.test.base import NonAtomicBaseTest

from posthog.hogql.query import execute_hogql_query

from posthog.models import User

from products.annotations.backend.facade.enums import AnnotationScope
from products.annotations.backend.models.annotation import Annotation


class TestSystemAnnotationsTable(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_personal_annotations_are_read_only_by_their_creator(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other-annotator@example.com", None)
        for content, scope, created_by in [
            ("shared", AnnotationScope.PROJECT, other_user),
            ("mine", AnnotationScope.USER, self.user),
            ("theirs", AnnotationScope.USER, other_user),
        ]:
            Annotation.objects.create(
                team=self.team, organization=self.organization, content=content, scope=scope, created_by=created_by
            )

        response = execute_hogql_query(
            "SELECT content FROM system.annotations ORDER BY content", team=self.team, user=self.user
        )

        assert [row[0] for row in response.results] == ["mine", "shared"]
