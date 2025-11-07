import json
import os
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def load_session_data(json_path: str) -> list[dict]:
    """Load session data from JSON file."""
    with open(json_path, "r") as f:
        return json.load(f)


def deduplicate_sessions(sessions: list[dict]) -> dict[str, str]:
    """
    Deduplicate sessions by UUID, keeping the first occurrence.
    Returns a dict mapping UUID to content_location.
    """
    unique_sessions = {}
    for session in sessions:
        uuid = session["uuid"]
        content_location = session["content_location"]
        if uuid not in unique_sessions:
            unique_sessions[uuid] = content_location
    return unique_sessions


def get_s3_client():
    """
    Create and return an S3 client.
    Supports both AWS SSO profiles and direct credentials via environment variables.
    """
    aws_profile = os.getenv("AWS_PROFILE")
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region = os.getenv("AWS_REGION", "us-east-1")
    s3_endpoint = os.getenv("S3_ENDPOINT")

    client_kwargs = {"service_name": "s3"}

    # Use profile if specified (for SSO), otherwise use explicit credentials
    if aws_profile:
        print(f"Using AWS profile: {aws_profile}")
        session = boto3.Session(profile_name=aws_profile)
        client_kwargs["region_name"] = aws_region
        if s3_endpoint:
            client_kwargs["endpoint_url"] = s3_endpoint
        return session.client(**client_kwargs)
    elif aws_access_key_id and aws_secret_access_key:
        print("Using AWS credentials from environment variables")
        client_kwargs.update({
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "region_name": aws_region,
        })
        if s3_endpoint:
            client_kwargs["endpoint_url"] = s3_endpoint
        return boto3.client(**client_kwargs)
    else:
        raise ValueError(
            "Either AWS_PROFILE or (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY) "
            "environment variables must be set"
        )



def download_video(
    s3_client,
    bucket: str,
    s3_key: str,
    local_path: str,
) -> tuple[bool, Optional[str]]:
    """
    Download a file from S3 to local path.
    Returns (success: bool, error_message: Optional[str]).
    """
    try:
        s3_client.download_file(bucket, s3_key, local_path)
        return True, None
    except (BotoCoreError, ClientError) as e:
        return False, str(e)


def main():
    # Configuration
    script_dir = Path(__file__).parent
    json_path = script_dir / "query_result_2025-11-07T08_41_37.748076Z.json"
    output_dir = script_dir / "videos"
    bucket_name = "posthog-cloud-prod-us-east-1-app-assets"

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load and deduplicate session data
    print(f"Loading session data from {json_path}...")
    sessions = load_session_data(str(json_path))
    print(f"Loaded {len(sessions)} total sessions")

    unique_sessions = deduplicate_sessions(sessions)
    print(f"Found {len(unique_sessions)} unique sessions (after deduplication)")

    # Initialize S3 client
    print("Connecting to S3...")
    try:
        s3_client = get_s3_client()
    except ValueError as e:
        print(f"Error: {e}")
        return

    # Download videos
    print(f"\nDownloading videos to {output_dir}...")
    success_count = 0
    failure_count = 0

    for i, (uuid, content_location) in enumerate(unique_sessions.items(), 1):
        local_filename = f"{uuid}.webm"
        local_path = output_dir / local_filename

        print(f"[{i}/{len(unique_sessions)}] Downloading {uuid}...", end=" ")

        success, error = download_video(
            s3_client=s3_client,
            bucket=bucket_name,
            s3_key=content_location,
            local_path=str(local_path),
        )

        if success:
            file_size_mb = local_path.stat().st_size / (1024 * 1024)
            print(f" ({file_size_mb:.2f} MB)")
            success_count += 1
        else:
            print(f" Error: {error}")
            failure_count += 1

    # Print summary
    print("\n" + "=" * 60)
    print("Download Summary:")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {failure_count}")
    print(f"  Total: {len(unique_sessions)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
