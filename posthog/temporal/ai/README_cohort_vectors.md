# Cohort Vector Sync Workflow

This workflow embeds cohorts similar to how actions are embedded in the `sync_vectors.py` workflow.

## Overview

The `SyncCohortVectorsWorkflow` processes cohorts in batches to:

1. Generate AI summaries of cohorts using the `CohortSummarizer`
2. Create embeddings from the summaries using Azure OpenAI
3. Sync the embeddings to ClickHouse for vector search

## Usage

### Running the Workflow

You can run the cohort vector sync workflow using the Temporal management command:

```bash
python manage.py execute_temporal_workflow ai-sync-cohort-vectors '{"summarize_batch_size": 96, "embed_batch_size": 96, "max_parallel_requests": 5, "insert_batch_size": 10000, "delay_between_batches": 60}' --task-queue max-ai
```

### Parameters

- `summarize_batch_size`: How many cohorts to summarize in a single batch (default: 96)
- `embed_batch_size`: How many cohorts to embed in a single batch (default: 96)
- `max_parallel_requests`: Maximum parallel requests to send to vendors (default: 5)
- `insert_batch_size`: How many rows to insert in a single query to ClickHouse (default: 10000)
- `delay_between_batches`: Seconds to wait between batches (default: 60)
- `embedding_version`: Version of the embedding model to use (optional)

### Example with Custom Parameters

```bash
python manage.py execute_temporal_workflow ai-sync-cohort-vectors '{"summarize_batch_size": 48, "embed_batch_size": 48, "max_parallel_requests": 3, "insert_batch_size": 5000, "delay_between_batches": 30, "embedding_version": 2}' --task-queue max-ai
```

## Database Changes

The workflow requires the following fields to be added to the Cohort model:

- `summary`: TextField for AI-generated summary
- `last_summarized_at`: DateTimeField for tracking when summarization occurred
- `embedding_last_synced_at`: DateTimeField for tracking when embedding sync occurred
- `embedding_version`: PositiveSmallIntegerField for tracking embedding model version
- `updated_at`: DateTimeField for tracking when the cohort was last updated

These fields are added via migrations:

- `0868_add_cohort_ai_fields.py`
- `0869_add_cohort_updated_at.py`

## Workflow Activities

1. **get_approximate_cohorts_count**: Gets the count of cohorts that need summarization
2. **batch_summarize_cohorts**: Summarizes cohorts in batches using CohortSummarizer
3. **batch_embed_and_sync_cohorts**: Embeds cohort summaries and syncs to ClickHouse

## Error Handling

The workflow includes comprehensive error handling:

- Individual cohort summarization failures don't stop the entire batch
- Azure API errors are properly handled and logged
- Retry policies are configured for transient failures
- Heartbeat timeouts prevent long-running activities from timing out

## Monitoring

The workflow logs progress and errors using structured logging. Key metrics to monitor:

- Number of cohorts processed per batch
- Summarization success/failure rates
- Embedding generation success/failure rates
- ClickHouse sync performance
