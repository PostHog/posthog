# API Example Service

A simple HTTP API service demonstrating Go service structure in PostHog.

## Endpoints

-   `GET /health` - Health check endpoint
-   `GET /config` - Shows current PostHog configuration

## Environment Variables

Required:

-   `POSTHOG_PROJECT_ID` - PostHog project ID
-   `POSTHOG_API_KEY` - PostHog API key
-   `INSTANCE_ID` - Instance identifier

Optional:

-   `POSTHOG_HOST` - PostHog host (defaults to https://app.posthog.com)

## Development

```bash
# Run the service
go run main.go

# Build the service
go build -o apiexample

# Run tests
go test ./...
```

## Docker

```bash
# Build the image
docker build -t posthog/apiexample .

# Run the container
docker run -p 8000:8000 \
  -e POSTHOG_PROJECT_ID=your_project_id \
  -e POSTHOG_API_KEY=your_api_key \
  -e INSTANCE_ID=your_instance_id \
  posthog/apiexample
```
