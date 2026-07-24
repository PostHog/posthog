---
name: downloading-batch-export-files
description: >
  Export PostHog events, persons, or sessions on demand and download the resulting files. Use when the user asks to
  download/export raw PostHog data, create a one-off file export, fetch a Parquet or JSONLines export, or use the
  file_download_batch_exports API. Covers starting the export with MCP, polling completion, and downloading via the
  existing REST redirect endpoint.
---

# Downloading batch export files

Use this skill when a user wants a one-off downloadable export of PostHog data.
The export is started and monitored through MCP, but the final file download uses the existing REST endpoint directly.

## Available MCP tools

| Tool                                           | Purpose                                                  |
| ---------------------------------------------- | -------------------------------------------------------- |
| `posthog:file-download-batch-exports-create`   | Start an on-demand export and return the run ID          |
| `posthog:file-download-batch-exports-retrieve` | Poll the run status and return file IDs after completion |

Do not rely on a generated MCP tool for the `/download/` endpoint.
That endpoint is a redirecting file download endpoint, so raw HTTP/download handling is the right interface until MCP has explicit redirect support.

## Workflow

### 1. Choose the export shape

Ask a short clarifying question if the user did not specify the required inputs:

- `model`: one of `events`, `persons`, or `sessions`
- `data_interval_start` and `data_interval_end`: ISO 8601 datetimes; the range must be at most one week
- `file.format`: `Parquet` or `JSONLines`; prefer `Parquet` for compact analytics exports and `JSONLines` for line-oriented text processing
- `file.compression`: optional, one of `zstd`, `gzip`, `brotli`, `lz4`, or `snappy`. If `JSONLines` was chosen as format, only `gzip` and `brotli` are supported.
- `file.max_size_mb`: optional maximum part size in MB; set this when the user wants multiple smaller files instead of a single (potentially large) file.

For `events`, `include` and `exclude` are optional event-name filters.
Use them only when the user asks for specific events or wants to omit specific events.

### 2. Start the export

Call `posthog:file-download-batch-exports-create` with the selected shape.
The response contains an `id` for the export run.

Example request:

```json
{
  "model": "events",
  "file": {
    "format": "JSONLines",
    "compression": "gzip"
  },
  "include": ["$pageview"],
  "data_interval_start": "2026-05-25T00:00:00Z",
  "data_interval_end": "2026-05-26T00:00:00Z"
}
```

### 3. Poll until completion

Call `posthog:file-download-batch-exports-retrieve` with the returned `id`.

Status handling:

| Status                                                                    | Action                                        |
| ------------------------------------------------------------------------- | --------------------------------------------- |
| `Starting` or `Running`                                                   | Wait briefly and poll again                   |
| `Completed`                                                               | Read the `files` array and download each file |
| `Cancelled`                                                               | Stop and report that the run was cancelled    |
| `Failed`, `FailedRetryable`, `FailedBilling`, `Terminated`, or `TimedOut` | Stop and report the `error` field             |

When `Completed`, the `files` array contains file UUIDs.
For single-file exports it usually contains one UUID.
For split exports, download every UUID unless the user asked for a specific part.

### 4. Optionally, cancel a running export

If required by the user, a running export can be cancelled by calling `posthog:file-download-batch-exports-cancel-create` with the returned `id`.

An export that has already finished or has already failed may not be cancelled.

After cancelling an export, the `id` may not be used anymore and the export must start again from the beginning. However, you may still use the `id` to retrieve the export status (which will always be `Cancelled`).

### 5. Download files through REST

Use a direct authenticated HTTP request to the existing endpoint:

```text
GET /api/projects/{project_id}/file_download_batch_exports/{run_id}/download/{part}/
```

`part` can be either:

- a file UUID from the `files` array returned by `file-download-batch-exports-retrieve`
- a zero-based file index, ordered by key

If there is only one file, this also works without `part`:

```text
GET /api/projects/{project_id}/file_download_batch_exports/{run_id}/download/
```

Let the HTTP client follow the redirect, or inspect the `Location` header if you need the temporary signed URL.
Use the same PostHog authentication context as other API calls.

### 6. Save, do not print, file contents

Treat the result as a file download, not a chat response.
Parquet is binary and must be written as bytes.
JSONLines may still be large; save it to a file rather than pasting the contents unless the user explicitly asks for a tiny sample.

Use a filename that includes the model, run ID, and part identifier when possible, for example:

```text
posthog-events-<run_id>-<part>.jsonl.gz
posthog-persons-<run_id>-<part>.parquet
```

## Watch-outs

- The maximum export interval is one week. Split longer user requests into separate export runs or ask which week to export.
- A run can briefly report `Running` after completion while file records are being created. Poll again instead of failing immediately.
- Download URLs are temporary. If a URL expires, call the REST download endpoint again for a fresh redirect.
- Do not send the signed URL to unrelated services unless the user explicitly asks; it grants temporary access to the exported file.
- If the user wants all parts of a split export, iterate over every UUID in `files`; do not assume part `0` is enough.
- Large batch exports may take a few minutes or even longer to complete. Suggest to the user that they can speed-up their download by including only certain events or narrowing the date range.
