#!/bin/bash
# LocalStack initialization script
# Runs when LocalStack is ready to accept requests

echo "🚀 Initializing LocalStack S3 buckets..."

# Create the posthog bucket (used for session recordings, etc.)
awslocal s3 mb s3://posthog 2>/dev/null || true

echo "✅ LocalStack S3 bucket 'posthog' is ready"

