# PostHog Synthetic Monitoring Lambda Function

This AWS Lambda function performs HTTP health checks for PostHog's synthetic monitoring feature.

## Deployment

### Prerequisites

- AWS CLI configured with appropriate credentials
- Python 3.12 runtime

### Deploy to a Single Region

```bash
# Create deployment package
cd lambda/synthetic-monitor
zip lambda.zip lambda_function.py

# Create IAM role (first time only)
aws iam create-role \
  --role-name posthog-synthetic-monitor-lambda \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach basic execution policy
aws iam attach-role-policy \
  --role-name posthog-synthetic-monitor-lambda \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Create the function
aws lambda create-function \
  --function-name posthog-synthetic-monitor \
  --runtime python3.12 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/posthog-synthetic-monitor-lambda \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda.zip \
  --timeout 30 \
  --memory-size 256 \
  --region us-east-1
```

### Deploy to Multiple Regions

Use the provided deployment script:

```bash
./deploy.sh
```

Or manually for each region:

```bash
for region in us-east-1 us-west-2 eu-west-1 ap-southeast-1; do
  aws lambda create-function \
    --function-name posthog-synthetic-monitor \
    --runtime python3.12 \
    --role arn:aws:iam::YOUR_ACCOUNT_ID:role/posthog-synthetic-monitor-lambda \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://lambda.zip \
    --timeout 30 \
    --memory-size 256 \
    --region $region
done
```

### Update Existing Function

```bash
# Update function code
aws lambda update-function-code \
  --function-name posthog-synthetic-monitor \
  --zip-file fileb://lambda.zip \
  --region us-east-1
```

## Configuration

### Environment Variables

Configure these in PostHog settings (not in Lambda):

- `AWS_ACCESS_KEY_ID`: AWS credentials with lambda:InvokeFunction permission
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
- `SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME`: Function name (default: `posthog-synthetic-monitor`)

### IAM Policy for PostHog

PostHog needs permission to invoke the Lambda function:

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

## Supported Regions

Common regions for deployment:

- `us-east-1` (N. Virginia)
- `us-west-2` (Oregon)
- `eu-west-1` (Ireland)
- `eu-central-1` (Frankfurt)
- `ap-southeast-1` (Singapore)
- `ap-northeast-1` (Tokyo)

## Testing

Test the function locally:

```bash
aws lambda invoke \
  --function-name posthog-synthetic-monitor \
  --payload '{"url":"https://posthog.com","method":"GET","expected_status_code":200,"timeout_seconds":10}' \
  --region us-east-1 \
  response.json

cat response.json
```

## Cost Estimation

- Lambda invocations: First 1M requests/month are free, then $0.20 per 1M requests
- Lambda duration: 400,000 GB-seconds free per month, then $0.00001667 per GB-second
- Example: 100 monitors × 5 min frequency × 30 days = 864,000 invocations/month
  - Cost: Free tier covers this usage
  - Each invocation ~200ms × 256MB = minimal cost

## Monitoring

View Lambda logs in CloudWatch:

```bash
aws logs tail /aws/lambda/posthog-synthetic-monitor --follow --region us-east-1
```
