

import dlt
from django.conf import settings
from .stripe import stripe_source

def run_stripe_pipeline(stripe_key: str):
    pipeline = dlt.pipeline(
        pipeline_name='stripe_pipeline',
        destination='filesystem',
        dataset_name='stripe_team_id_1',
        credentials={
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
        }
    )

    source = stripe_source(stripe_secret_key=stripe_key)
    load_info = pipeline.run(source, loader_file_format="parquet")
    print(load_info)