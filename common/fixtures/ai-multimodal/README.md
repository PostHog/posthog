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

    OPENAI_API_KEY=sk-... python common/fixtures/ai-multimodal/record_fixture.py

The screenshot must stay above `AI_BLOB_OFFLOAD_MIN_BASE64_LENGTH` (20480 base64 chars,
`nodejs/src/ingestion/config.ts:386`). Below that, ingestion leaves the image inline and
both tests pass while covering nothing. The recorder enforces this.
