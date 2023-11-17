import dlt
from django.conf import settings
from .stripe import stripe_source
from dataclasses import dataclass


@dataclass
class PipelineInputs:
    job_type: str
    team_id: int


def create_pipeline(inputs: PipelineInputs):
    return dlt.pipeline(
        pipeline_name=f"{inputs.job_type}_pipeline",
        destination="filesystem",
        dataset_name=f"{inputs.job_type}_team_{inputs.team_id}",
        credentials={
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
        },
    )


@dataclass
class StripeJobInputs(PipelineInputs):
    stripe_secret_key: str


def run_stripe_pipeline(inputs: StripeJobInputs):
    pipeline = create_pipeline(inputs)

    # TODO: decouple API calls so they can be incrementally read and sync_rows updated
    source = stripe_source(stripe_secret_key=inputs.stripe_secret_key)
    pipeline.run(source, loader_file_format="parquet")


PIPELINE_TYPE_INPUTS_MAPPING = {"Stripe": StripeJobInputs}
PIPELINE_TYPE_MAPPING = {"Stripe": run_stripe_pipeline}
