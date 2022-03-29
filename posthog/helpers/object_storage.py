"""
Helpers to interact with our Object Storage system
"""
import boto3
from botocore.client import Config

s3 = boto3.resource(
    "s3",
    endpoint_url="http://localhost:19000",
    aws_access_key_id="object_storage_root_user",
    aws_secret_access_key="object_storage_root_password",
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def generate_big_random_bin_file(filename, size):
    """
    generate big binary file with the specified size in bytes
    :param filename: the filename
    :param size: the size in bytes
    :return:void
    """
    import os

    with open(filename, "wb") as file:
        file.write(os.urandom(size))
    pass


random_file = generate_big_random_bin_file("/tmp/test", 10 * 1024 * 1024)
s3.Bucket("posthog").upload_file("/tmp/test", "test")
