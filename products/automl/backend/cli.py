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
    "--eval-fraction",
    type=float,
    default=0.2,
    show_default=True,
    help="Random holdout fraction used to score the leaderboard.",
)
@click.option("--presets", default="medium_quality", show_default=True)
@click.option("--eval-metric", default=None, help="AutoGluon eval metric (auto if omitted).")
@click.option("--experiment-name", default="automl-hackathon", show_default=True)
@click.option("--s3-region", default=None, help="Override AWS region for S3 reads/writes.")
def run(
    train_parquet: str,
    target: str,
    predictions_output: str,
    id_column: str,
    model_dir: Optional[str],
    where: Optional[str],
    time_limit_s: int,
    eval_fraction: float,
    presets: str,
    eval_metric: Optional[str],
    experiment_name: str,
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
        eval_fraction=eval_fraction,
        presets=presets,
        eval_metric=eval_metric,
        experiment_name=experiment_name,
        s3_region=s3_region,
    )
    click.echo(json.dumps(asdict(result), indent=2, default=str))


if __name__ == "__main__":
    cli()
