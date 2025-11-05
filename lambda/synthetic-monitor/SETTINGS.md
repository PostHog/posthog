# PostHog Settings for Synthetic Monitoring

## Required Django Settings

Add these settings to your PostHog configuration (e.g., `posthog/settings.py` or environment variables):

### AWS Lambda Configuration

```python
# Lambda function name (should match the deployed function name)
SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME = "posthog-synthetic-monitor"
```

### AWS Credentials

PostHog needs AWS credentials with `lambda:InvokeFunction` permission. Configure via:

**Option 1: Environment Variables** (recommended)

```bash
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
# Optional: Default region (will be overridden by monitor's region settings)
export AWS_DEFAULT_REGION="us-east-1"
```

**Option 2: IAM Role** (for EC2/ECS deployments)

If PostHog runs on AWS infrastructure, attach an IAM role with this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:*:YOUR_ACCOUNT_ID:function:posthog-synthetic-monitor"
    }
  ]
}
```

**Option 3: Django Settings**

```python
# Not recommended for production (use environment variables instead)
AWS_ACCESS_KEY_ID = "your-access-key-id"
AWS_SECRET_ACCESS_KEY = "your-secret-access-key"
```

## Environment Variables Summary

For production deployment, set these environment variables:

```bash
# Required
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Optional
SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME=posthog-synthetic-monitor  # defaults to "posthog-synthetic-monitor"
AWS_DEFAULT_REGION=us-east-1  # optional, each monitor can specify regions
```

## IAM User Setup (for AWS_ACCESS_KEY_ID method)

Create a dedicated IAM user for PostHog:

```bash
# Create IAM user
aws iam create-user --user-name posthog-synthetic-monitoring

# Create access key
aws iam create-access-key --user-name posthog-synthetic-monitoring

# Create and attach inline policy
aws iam put-user-policy \
  --user-name posthog-synthetic-monitoring \
  --policy-name LambdaInvokePolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:*:YOUR_ACCOUNT_ID:function:posthog-synthetic-monitor"
    }]
  }'
```

Replace `YOUR_ACCOUNT_ID` with your AWS account ID.

## Security Best Practices

1. **Use IAM Roles** when running PostHog on AWS (EC2, ECS, EKS)
2. **Rotate credentials** regularly if using access keys
3. **Principle of least privilege**: Only grant `lambda:InvokeFunction` permission
4. **Restrict by resource**: Use specific function ARN in IAM policy
5. **Monitor usage**: Enable CloudTrail for Lambda invocation auditing

## Testing Configuration

Verify your AWS credentials work:

```python
# In Django shell (python manage.py shell)
import boto3
from django.conf import settings

# Test Lambda client creation
client = boto3.client('lambda', region_name='us-east-1')

# Test Lambda invocation
response = client.invoke(
    FunctionName=settings.SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME,
    InvocationType='RequestResponse',
    Payload='{"url":"https://posthog.com","method":"GET","expected_status_code":200}'
)

print(response)
```

## Troubleshooting

### "AccessDeniedException" when invoking Lambda

- Check AWS credentials are configured correctly
- Verify IAM policy allows `lambda:InvokeFunction`
- Ensure function ARN in policy matches deployed function

### "ResourceNotFoundException"

- Verify Lambda function is deployed in the target region
- Check `SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME` matches deployed function name
- Run `aws lambda list-functions --region us-east-1` to see available functions

### "TooManyRequestsException"

- Lambda is being throttled due to concurrent execution limits
- Increase Lambda concurrent execution limit in AWS console
- Reduce monitor check frequency or number of monitors
