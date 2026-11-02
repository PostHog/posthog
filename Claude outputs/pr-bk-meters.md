**Title:** feat(business-knowledge): meter chunk ingestion and knowledge queries

## Problem

The Business Knowledge pricing RFC (requests-for-comments-internal#1333) proposes two meters, chunks ingested and queries, but we have no data on either per organization. We aren't ready to charge yet. This is step 1 of splitting #123350: record usage, so we can check the RFC's prices against real usage before anything is billed.

## Changes

- New append-only ledger, `KnowledgeUsageRecord`. Every chunk write adds a row in the same transaction as the chunks. Every search made with a `RetrievalTrace` adds one query row (API, support, PostHog AI, docs shadow, learning).
- Query rows are idempotent on trace ID. Support and learning derive stable trace IDs from the Temporal activity or the learning run, so a retry counts once.
- Recording fails open: a ledger error is logged and never fails an ingest or search.
- Nothing user-visible. No usage report, billing service, quotas or UI. The hard caps stay.
- Mechanical: migration `0025`, IDOR semgrep entries.

## How did you test this code?

New `test_billing.py` and `test_retrieve_metering.py`; the learning analyzer test now checks the search's trace. I only ran `ruff format` and `ruff check`. The pytest suites, mypy and `makemigrations --check` were not run.

**Test rationale:** the ledger becomes the billing source of truth, so each test pins one metering rule: every ingest path is counted, rollbacks count nothing, retries count once, and a ledger error never fails the work. No existing test checks what gets counted.

## Release status

- No feature flag controls this change <!-- release-status: no-feature-flag -->
