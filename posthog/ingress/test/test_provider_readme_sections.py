from pathlib import Path

from django.test import SimpleTestCase

INGRESS_ROOT = Path(__file__).resolve().parent.parent

# A provider folder is one with a `provider.py` (it dispatches) or a `scheme.py` (it feeds the
# DRF adapter path). Both kinds carry a README.
PROVIDER_MODULES = ("provider.py", "scheme.py")

# The same headings in the same order for every provider, so a reader finds a provider's facts
# in one place, instead of in paragraphs that collide in the package README.
REQUIRED_SECTIONS = [
    "Headers",
    "Signature scheme",
    "Delivery id and event type",
    "Apps and secrets",
    "Quirks",
    "Consumers",
]


def provider_directories() -> list[Path]:
    directories = {path.parent for module in PROVIDER_MODULES for path in INGRESS_ROOT.glob(f"*/{module}")}
    return sorted(directories)


def section_headings(readme: Path) -> list[str]:
    lines = readme.read_text(encoding="utf-8").splitlines()
    return [line.removeprefix("## ").strip() for line in lines if line.startswith("## ")]


class TestProviderReadmeSections(SimpleTestCase):
    def test_every_provider_folder_has_a_readme_with_the_fixed_sections(self) -> None:
        directories = provider_directories()
        self.assertTrue(directories, "no provider folders found under posthog/ingress/")

        for directory in directories:
            with self.subTest(provider=directory.name):
                readme = directory / "README.md"
                self.assertTrue(readme.is_file(), f"{directory.name}/ has no README.md")
                self.assertEqual(section_headings(readme), REQUIRED_SECTIONS)
