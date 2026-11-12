from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.refs import uuid_ref_key, uuid_ref_key_expression

CANONICAL = "abcdef12-3456-4890-abcd-ef1234567890"


class TestUuidRefKey(BaseTest):
    @parameterized.expand(
        [
            ("canonical", CANONICAL),
            ("uppercase", CANONICAL.upper()),
            ("mixed_case", "AbCdEf12-3456-4890-AbCd-Ef1234567890"),
            ("no_hyphens", CANONICAL.replace("-", "")),
            ("braces", "{" + CANONICAL + "}"),
            ("one_brace", "{" + CANONICAL),
            ("urn", "urn:uuid:" + CANONICAL),
            ("uppercase_urn", "URN:UUID:" + CANONICAL),
            ("stray_hyphens", "-" + CANONICAL.replace("-", "") + "--"),
            ("trailing_newline", CANONICAL + "\n"),
            ("leading_space", " " + CANONICAL),
            ("hex_prefix", "0x" + "a" * 30),
            ("unicode_digit", "١" + CANONICAL[1:]),
            ("too_short", CANONICAL[:-1]),
            ("too_long", CANONICAL + "0"),
            ("integer", "42"),
        ]
    )
    def test_python_and_sql_compute_the_same_key(self, _name: str, ref: str) -> None:
        row = FileSystem.objects.create(team=self.team, path="Synthetic", depth=1, type="hog_flow", ref=ref)

        sql_key = (
            FileSystem.objects.filter(pk=row.pk)
            .annotate(key=uuid_ref_key_expression())
            .values_list("key", flat=True)
            .get()
        )

        self.assertEqual(sql_key, uuid_ref_key(ref))
