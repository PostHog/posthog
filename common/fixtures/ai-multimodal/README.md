# Shared multimodal AI fixture

`generation-event.json` is a real `$ai_generation` event, recorded from an actual
`posthog.ai.openai` call against OpenAI with `screenshot.png` attached. It is the
single source of truth for both halves of the multimodal ingestion E2E coverage.

## Consumers — both must be updated together

- `common/ingestion/acceptance_tests/test_ai_multimodal_blessed_path.py` (ingestion)
- `products/ai_observability/frontend/e2e/multimodal-trace.spec.ts` (rendering)

These two tests only constitute end-to-end coverage *together*: one proves the event
reaches ClickHouse as a blob pointer, the other proves the pointer renders. If you change
one side without the other, both can stay green while the end-to-end property is broken.
They will be merged into a single Playwright spec once the Node SDK supports AI capture.

## Regenerating

Run from the repo root:

    OPENAI_API_KEY="$(op read 'op://General/sbadkrbtbdgev4mjm4xtuirfoy/credential' --account posthog.1password.com)" \
    OPENAI_BASE_URL="https://api.openai.com/v1" \
      ./common/ingestion/acceptance_tests/.venv/bin/python common/fixtures/ai-multimodal/record_fixture.py

Both overrides are load-bearing:

- **The interpreter must be the acceptance venv's**, because that is where the `openai` package this
  script drives is installed. Create it with
  `python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt` in
  `common/ingestion/acceptance_tests`. Both that venv and the monorepo install the PostHog SDK under
  the same name, `posthoganalytics` — deliberately, since importing it as `posthog` resolves to this
  repo's own Django app and breaks type checking.
- **`OPENAI_BASE_URL` must be forced to the real API.** Some local and agent environments set it
  to a proxy that applies its own model allowlist and rejects the request with a misleading
  `403 Model 'gpt-4o-mini' not allowed for product 'posthog_code'` — which looks like a key
  problem but is not.

`.env.local` stores `op://` references rather than literal secrets, hence reading the key through
`op` above. `op read` needs interactive 1Password approval and intermittently fails with
`error initializing client: authorization timeout`; retry when that happens. If the fetch fails it
yields an *empty* key and OpenAI then answers `401 ... You didn't provide an API key`, so check the
key resolved before blaming the credential.

The screenshot must stay above `AI_BLOB_OFFLOAD_MIN_BASE64_LENGTH` (20480 base64 chars,
`nodejs/src/ingestion/config.ts:386`). Below that, ingestion leaves the image inline and
both tests pass while covering nothing. The recorder enforces this.
