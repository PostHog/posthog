# Max AI Setup for Hobby Deployments

This guide explains how to enable Max AI (PostHog's AI assistant) on self-hosted hobby deployments.

## Prerequisites

**Required:**
- `OPENAI_API_KEY` - Get from [OpenAI Platform](https://platform.openai.com/api-keys)

**Optional:**
- `ANTHROPIC_API_KEY` - Only needed for the `/ticket` support command. Get from [Anthropic Console](https://console.anthropic.com/)

## Setup

### 1. Add API Keys to Environment

Add your OpenAI API key to your `.env` file or export as an environment variable:

```bash
export OPENAI_API_KEY="sk-proj-..."

# Optional: only if you want to use the /ticket command
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 2. Start the Services

The `docker-compose.hobby.yml` file already includes:
- `TEMPORAL_HOST: temporal` on the web service (for Temporal connectivity)
- `temporal-django-worker-max-ai` service (dedicated worker for Max AI)

Start all services:

```bash
docker-compose -f docker-compose.hobby.yml up -d
```

Or if you're updating an existing deployment:

```bash
docker-compose -f docker-compose.hobby.yml up -d --force-recreate web temporal-django-worker-max-ai
```

### 3. Verify Setup

Check that the Max AI worker is running and listening on the correct queue:

```bash
docker-compose logs temporal-django-worker-max-ai --tail 20
```

You should see:
```
"task_queue": "max-ai-task-queue"
```

## Troubleshooting

### "Stream for this conversation not available"

This error means the Temporal workflow failed. Check:

1. **Worker logs**: `docker-compose logs temporal-django-worker-max-ai --tail 50`
2. **OpenAI API key is set**: `docker-compose exec temporal-django-worker-max-ai printenv | grep OPENAI_API_KEY`
3. **Task queue is correct**: Should show `max-ai-task-queue` in the worker startup logs

### Web container can't connect to Temporal

If you see `Connection refused` errors to `127.0.0.1:7233`:

```bash
docker-compose exec web printenv | grep TEMPORAL_HOST
```

Should output: `TEMPORAL_HOST=temporal`

If not, ensure `TEMPORAL_HOST: temporal` is set in the web service environment and recreate the container:

```bash
docker-compose up -d --force-recreate web
```

### Empty streaming response

If the POST to `/api/environments/{id}/conversations/` returns an empty stream:

1. Check web logs: `docker-compose logs web --tail 30`
2. Check worker logs: `docker-compose logs temporal-django-worker-max-ai --tail 30`
3. Verify Temporal is healthy: `docker-compose logs temporal --tail 20`

## Architecture

Max AI uses Temporal for workflow orchestration:

```
Browser → Web (starts workflow) → Temporal → temporal-django-worker-max-ai (runs AI) → Redis (streams) → Web → Browser
```

The dedicated `max-ai-task-queue` ensures AI workloads are isolated from other Temporal workflows.
