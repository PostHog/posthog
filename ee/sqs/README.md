# SQS Integration

This module provides infrastructure for consuming and producing messages via AWS SQS queues.

## Architecture

- `SQSConsumer` - Abstract base class for consuming messages from SQS
- `SQSProducer` - Class for sending messages to SQS queues
- `ee/billing/queue/BillingConsumer` - Billing-specific consumer implementation

## Local development

For local development, we use LocalStack to emulate AWS SQS. The billing service runs its own LocalStack instance that creates the queues PostHog consumes from.

### Prerequisites

1. The billing service must be running with LocalStack:

   ```bash
   cd ../billing
   docker-compose up -d localstack
   ```

2. Add SQS configuration to your `.env` file:

   ```bash
   # SQS Configuration - LocalStack (consumes from billing service's LocalStack)
   SQS_BILLING_QUEUE_URL=http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/billing-to-posthog-us
   SQS_BILLING_REGION=us-east-1

   # AWS credentials for LocalStack
   AWS_ACCESS_KEY_ID=test
   AWS_SECRET_ACCESS_KEY=test
   ```

### Running the consumer

```bash
# Run continuously (recommended for development)
python manage.py consume_sqs --queue billing --continuous

# Process a single batch of messages
python manage.py consume_sqs --queue billing

# Adjust batch size (default: 10, max: 10)
python manage.py consume_sqs --queue billing --max-messages 5 --continuous
```

## Queue configuration

Queues are configured in `ee/settings.py`:

```python
SQS_QUEUES = {
    "billing": {
        "url": get_from_env("SQS_BILLING_QUEUE_URL", optional=True),
        "region": get_from_env("SQS_BILLING_REGION", "us-east-1", optional=True),
        "type": "billing",
    },
}
```

## Message types

The billing consumer handles these message types:

| Type | Description |
|------|-------------|
| `billing_customer_update` | Updates organization billing status from the billing service |
| `invoice_finalized` | Triggers marketplace invoice submission (for Vercel integration) |
| `marketplace.invoice.submit` | Explicit request to submit an invoice to a marketplace |
| `marketplace.usage.submit` | Explicit request to submit usage data to a marketplace |

## Adding a new consumer

1. Create a new consumer class extending `SQSConsumer`:

   ```python
   from ee.sqs.SQSConsumer import SQSConsumer

   class MyConsumer(SQSConsumer):
       def process_message(self, message: dict) -> None:
           # Parse and process the message
           body = json.loads(message.get("Body", "{}"))
           # ... handle the message
           self.delete_message(message["ReceiptHandle"])
   ```

2. Register the consumer in `ee/management/commands/consume_sqs.py`:

   ```python
   def _get_consumer(self, queue_type: str, queue_url: str, region_name: str):
       if queue_type == "my_queue":
           return MyConsumer(queue_url=queue_url, region_name=region_name)
   ```

3. Add queue configuration to `ee/settings.py`

## Message format

Messages from the billing service are gzip-compressed and base64-encoded:

```python
{
    "type": "invoice_finalized",
    "organization_id": "org_123",
    "invoice_id": "inv_456",
    "period_start": 1699488000,
    "period_end": 1702080000
}
```

The `BillingConsumer` handles decompression automatically based on the `content_encoding` message attribute.
