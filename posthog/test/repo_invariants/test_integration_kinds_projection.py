from pathlib import Path

from hogli_commands.projections import PROJECTIONS, OutputFormatter, ProjectionRunner

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_generated_file_is_in_sync_with_the_catalogue() -> None:
    [projection] = [projection for projection in PROJECTIONS if projection.name == "integration-kinds"]
    runner = ProjectionRunner(REPO_ROOT, [projection], OutputFormatter(REPO_ROOT))

    assert runner.stale(projection) == [], "Run `hogli build:projections --only integration-kinds`."
