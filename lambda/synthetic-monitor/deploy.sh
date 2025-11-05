#!/usr/bin/env bash
set -e

# PostHog Synthetic Monitoring Lambda Deployment Script
#
# This script deploys the synthetic monitoring Lambda function to multiple AWS regions.
#
# Usage:
#   ./deploy.sh [--account-id YOUR_ACCOUNT_ID] [--regions "us-east-1 eu-west-1"]

# Configuration
FUNCTION_NAME="posthog-synthetic-monitor"
ROLE_NAME="posthog-synthetic-monitor-lambda"
RUNTIME="python3.12"
TIMEOUT=30
MEMORY_SIZE=256

# Default regions for global coverage
DEFAULT_REGIONS=(
  "us-east-1"      # N. Virginia
  "us-west-2"      # Oregon
  "eu-west-1"      # Ireland
  "ap-southeast-1" # Singapore
)

# Parse arguments
AWS_ACCOUNT_ID=""
REGIONS=("${DEFAULT_REGIONS[@]}")

while [[ $# -gt 0 ]]; do
  case $1 in
    --account-id)
      AWS_ACCOUNT_ID="$2"
      shift 2
      ;;
    --regions)
      IFS=' ' read -r -a REGIONS <<< "$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--account-id YOUR_ACCOUNT_ID] [--regions \"us-east-1 eu-west-1\"]"
      exit 1
      ;;
  esac
done

# Get AWS account ID if not provided
if [ -z "$AWS_ACCOUNT_ID" ]; then
  echo "Getting AWS account ID…"
  AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  echo "Using account ID: $AWS_ACCOUNT_ID"
fi

ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ROLE_NAME}"

# Create deployment package
echo "Creating deployment package…"
rm -f lambda.zip
zip lambda.zip lambda_function.py
echo "Deployment package created: lambda.zip"

# Check if role exists, create if not
echo "Checking IAM role…"
if ! aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  echo "Creating IAM role: $ROLE_NAME"

  # Create role
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' \
    --description "Execution role for PostHog Synthetic Monitoring Lambda"

  # Attach basic execution policy for CloudWatch Logs
  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

  echo "Waiting 10 seconds for IAM role to propagate…"
  sleep 10
else
  echo "IAM role already exists: $ROLE_NAME"
fi

# Deploy to each region
echo ""
echo "Deploying to regions: ${REGIONS[*]}"
echo ""

for region in "${REGIONS[@]}"; do
  echo "Deploying to $region…"

  # Check if function exists
  if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$region" &>/dev/null; then
    echo "  Function exists, updating code…"
    aws lambda update-function-code \
      --function-name "$FUNCTION_NAME" \
      --zip-file fileb://lambda.zip \
      --region "$region" \
      --output text \
      --query 'FunctionArn'
  else
    echo "  Creating new function…"
    aws lambda create-function \
      --function-name "$FUNCTION_NAME" \
      --runtime "$RUNTIME" \
      --role "$ROLE_ARN" \
      --handler lambda_function.lambda_handler \
      --zip-file fileb://lambda.zip \
      --timeout $TIMEOUT \
      --memory-size $MEMORY_SIZE \
      --region "$region" \
      --description "PostHog Synthetic Monitoring HTTP checker" \
      --output text \
      --query 'FunctionArn'
  fi

  echo "  Deployed to $region"
  echo ""
done

echo "Deployment complete!"
echo ""
echo "Function ARN pattern:"
echo "  arn:aws:lambda:<region>:${AWS_ACCOUNT_ID}:function:${FUNCTION_NAME}"
echo ""
echo "Next steps:"
echo "  1. Configure AWS credentials in PostHog with lambda:InvokeFunction permission"
echo "  2. Set SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME=${FUNCTION_NAME} in PostHog settings"
echo "  3. Update SyntheticMonitor.regions field to include: ${REGIONS[*]}"
