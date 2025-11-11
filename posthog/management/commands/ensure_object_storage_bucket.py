from django.conf import settings
from django.core.management.base import BaseCommand

import boto3
from botocore.config import Config


class Command(BaseCommand):
    help = "Ensure the default object storage bucket exists (idempotent)"

    def handle(self, *args, **options):
        endpoint = settings.OBJECT_STORAGE_ENDPOINT
        access_key = settings.OBJECT_STORAGE_ACCESS_KEY_ID
        secret_key = settings.OBJECT_STORAGE_SECRET_ACCESS_KEY
        region = getattr(settings, "OBJECT_STORAGE_REGION", "us-east-1")
        bucket = settings.OBJECT_STORAGE_BUCKET

        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path"}),
            region_name=region,
        )

        try:
            s3.create_bucket(Bucket=bucket)
            self.stdout.write(self.style.SUCCESS(f"Created bucket '{bucket}'"))
        except Exception as err:  # noqa: BLE001
            # If it already exists, treat as success; otherwise print diagnostic and continue
            self.stdout.write(f"Bucket create returned: {err}")
            self.stdout.write(self.style.WARNING(f"Assuming bucket '{bucket}' exists or was created concurrently"))
