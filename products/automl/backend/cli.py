"""CLI entry point for the AutoML hackathon prototype.

Usage:

    python -m products.automl.backend.cli generate-fixture /tmp/fixture.parquet --n-users 5000
    python -m products.automl.backend.cli run \\
        --train-parquet /tmp/fixture.parquet \\
        --target churned \\
        --predictions-output /tmp/predictions.parquet
"""

from __future__ import annotations

import sys
import json
import logging
from dataclasses import asdict
from typing import Optional

import click
import structlog

from products.automl.backend.data.loader import DataLoader
from products.automl.backend.data.posthog_source import PostHogClient
from products.automl.backend.data.synthetic import write_synthetic_parquet
from products.automl.backend.pipeline import run_end_to_end


def _configure_logging(level: str) -> None:
    level_int = getattr(logging, level.upper())
    logging.basicConfig(format="%(message)s", level=level_int, stream=sys.stderr)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        cache_logger_on_first_use=True,
    )


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    show_default=True,
)
def cli(log_level: str) -> None:
    """AutoML hackathon prototype."""
    _configure_logging(log_level)


@cli.command("prepare-from-hogql")
@click.option("--project-id", type=int, required=True, help="PostHog project (team) ID to query.")
@click.option(
    "--host",
    default="https://us.posthog.com",
    show_default=True,
    help="PostHog host. Use https://eu.posthog.com for EU cloud or your self-hosted URL.",
)
@click.option(
    "--api-key",
    default=None,
    help="Personal API key. Defaults to POSTHOG_PERSONAL_API_KEY env var.",
)
@click.option("--query", default=None, help="HogQL query string. Mutually exclusive with --query-file.")
@click.option(
    "--query-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to a file containing the HogQL query.",
)
@click.option("--output", required=True, help="Path or s3:// URL for the resulting parquet.")
@click.option("--s3-region", default=None, help="Override AWS region for S3 writes.")
@click.option(
    "--allow-truncated",
    is_flag=True,
    default=False,
    help="Accept a truncated HogQL response. By default the command errors if the server caps the result.",
)
@click.option(
    "--param",
    "params",
    multiple=True,
    metavar="KEY=VALUE",
    help="Substitute a {KEY} placeholder in the query (repeatable). Example: --param sample_pct=5",
)
@click.option(
    "--sample-pct",
    type=float,
    default=None,
    help=(
        "Person sample percentage. Floats supported (e.g. 0.5 for 0.5%%, 0.01 for 0.01%%). "
        "Substitutes {sample_threshold} = round(pct * 100) for use with `cityHash64(...) %% 10000 < N`. "
        "Default 10 if the query uses {sample_threshold}."
    ),
)
def prepare_from_hogql(
    project_id: int,
    host: str,
    api_key: Optional[str],
    query: Optional[str],
    query_file: Optional[str],
    output: str,
    s3_region: Optional[str],
    allow_truncated: bool,
    params: tuple[str, ...],
    sample_pct: Optional[float],
) -> None:
    """Execute a HogQL query against PostHog and write the result to parquet."""
    if not query and not query_file:
        raise click.UsageError("Provide either --query or --query-file.")
    if query and query_file:
        raise click.UsageError("--query and --query-file are mutually exclusive.")

    if query_file:
        with open(query_file) as f:
            query = f.read()
    assert query is not None

    param_dict: dict[str, str] = {}
    for raw in params:
        if "=" not in raw:
            raise click.UsageError(f"--param expects KEY=VALUE, got {raw!r}")
        key, value = raw.split("=", 1)
        param_dict[key.strip()] = value
    if sample_pct is not None:
        if not 0 < sample_pct <= 100:
            raise click.UsageError(f"--sample-pct must be in (0, 100], got {sample_pct}")
        param_dict["sample_threshold"] = str(int(round(sample_pct * 100)))
    elif "{sample_threshold}" in query and "sample_threshold" not in param_dict:
        param_dict["sample_threshold"] = "1000"

    for key, value in param_dict.items():
        query = query.replace(f"{{{key}}}", value)

    client = PostHogClient.from_env(project_id=project_id, host=host, api_key=api_key)
    df = client.run_hogql(query, allow_truncated=allow_truncated)

    with DataLoader(s3_region=s3_region) as loader:
        loader.write_parquet(df, output)

    click.echo(
        json.dumps(
            {
                "output_path": output,
                "rows": len(df),
                "columns": df.columns,
                "project_id": project_id,
                "host": host,
            },
            indent=2,
        )
    )


@cli.command("generate-fixture")
@click.argument("output_path", type=click.Path(dir_okay=False))
@click.option("--n-users", type=int, default=5000, show_default=True)
@click.option("--seed", type=int, default=42, show_default=True)
def generate_fixture(output_path: str, n_users: int, seed: int) -> None:
    """Write a synthetic per-user parquet for end-to-end testing."""
    write_synthetic_parquet(output_path, n_users=n_users, seed=seed)
    click.echo(f"wrote {n_users} rows to {output_path}")


@cli.command("run")
@click.option("--train-parquet", required=True, help="Path or s3:// URL to the training parquet.")
@click.option("--target", required=True, help="Name of the target column to predict.")
@click.option("--predictions-output", required=True, help="Path or s3:// URL for predictions parquet.")
@click.option("--id-column", default="user_id", show_default=True, help="Column carried through to predictions.")
@click.option(
    "--model-dir", type=click.Path(), default=None, help="Where to persist the AutoGluon model (defaults to tempdir)."
)
@click.option("--where", default=None, help="Optional raw SQL WHERE clause applied during load.")
@click.option(
    "--time-limit-s",
    type=int,
    default=60,
    show_default=True,
    help="AutoGluon training budget. Set low for pipecleaning.",
)
@click.option(
    "--val-fraction",
    type=float,
    default=0.15,
    show_default=True,
    help="Validation fraction passed to AutoGluon as tuning_data (HPO + model selection).",
)
@click.option(
    "--test-fraction",
    type=float,
    default=0.15,
    show_default=True,
    help="Held-out test fraction used only for final unbiased leaderboard scoring.",
)
@click.option("--presets", default="medium_quality", show_default=True)
@click.option("--eval-metric", default=None, help="AutoGluon eval metric (auto if omitted).")
@click.option("--s3-region", default=None, help="Override AWS region for S3 reads/writes.")
def run(
    train_parquet: str,
    target: str,
    predictions_output: str,
    id_column: str,
    model_dir: Optional[str],
    where: Optional[str],
    time_limit_s: int,
    val_fraction: float,
    test_fraction: float,
    presets: str,
    eval_metric: Optional[str],
    s3_region: Optional[str],
) -> None:
    """Load → train → predict → write parquet."""
    result = run_end_to_end(
        train_parquet=train_parquet,
        target=target,
        predictions_output=predictions_output,
        id_column=id_column,
        model_dir=model_dir,
        where=where,
        time_limit_s=time_limit_s,
        val_fraction=val_fraction,
        test_fraction=test_fraction,
        presets=presets,
        eval_metric=eval_metric,
        s3_region=s3_region,
    )
    click.echo(json.dumps(asdict(result), indent=2, default=str))


if __name__ == "__main__":
    cli()
