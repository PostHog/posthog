"""
Helpers to interact with our Object Storage system
"""
import boto3
from botocore.client import Config

# TODO: passing S3 settings
# TODO: read -> compress -> stream to s3 on the fligh (without touching the disk)
# TODO: we should pass to our client the compressed file and then decompress in the browser

s3 = boto3.resource(
    "s3",
    endpoint_url="http://localhost:19000",
    aws_access_key_id="object_storage_root_user",
    aws_secret_access_key="object_storage_root_password",
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def write(file_name: str, content: str):
    s3.Bucket("posthog").put_object(Body=content, Key=file_name)


def read(file_name: str):
    s3_object = s3.Object("posthog", file_name)
    content = s3_object.get()["Body"].read()
    return content.decode("utf-8")
