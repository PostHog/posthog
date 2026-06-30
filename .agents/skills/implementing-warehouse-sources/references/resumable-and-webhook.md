# Resumable and webhook source patterns

These patterns extend `source_for_pipeline` (see the SKILL body for the core return-shape rules).

## Resumable source pattern

```python
@dataclasses.dataclass
class MyResumeConfig:
    next_url: str  # or cursor, offset, time window — whatever the API uses

class MySource(ResumableSource[MySourceConfig, MyResumeConfig]):
    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MyResumeConfig]:
        return ResumableSourceManager[MyResumeConfig](inputs, MyResumeConfig)

    def source_for_pipeline(
        self,
        config: MySourceConfig,
        resumable_source_manager: ResumableSourceManager[MyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return my_source(..., resumable_source_manager=resumable_source_manager)
```

In the transport function:

```python
resume = manager.load_state() if manager.can_resume() else None
url = resume.next_url if resume else initial_url

while True:
    data = fetch_page(url)
    # yield batch
    next_url = data.get("links", {}).get("next")
    if not next_url:
        break
    manager.save_state(MyResumeConfig(next_url=next_url))
    url = next_url  # advance before the next fetch, otherwise we loop on the same page
```

Save state **after** yielding each batch, not before — so if we crash we re-yield the last batch (merge dedupes on primary key) rather than skipping it.

## Webhook source pattern

- Implement `webhook_template` returning a `HogFunctionTemplateDC` that transforms incoming webhook payloads.
- Implement `webhook_resource_map` mapping our schema name → external object type.
- Implement `create_webhook`, `delete_webhook`, `get_external_webhook_info` if the API allows programmatic webhook management. Otherwise return a failed result and provide a `webhookSetupCaption` explaining manual setup.
- Add `webhookFields` to `SourceConfig` for post-setup inputs (e.g. signing secret).
- In `source_for_pipeline`, call `self.get_webhook_source_manager(inputs)` and pass its iterator alongside the pull iterator so a single sync pulls historical + webhook-delivered rows.
- Populate `SourceSchema.supports_webhooks=True` only for endpoints where webhooks are actually viable (usually incremental/append-only ones).
- **De-dupe within a webhook batch with a `table_transformer`.** `WebhookSourceManager.get_items()` takes an optional `table_transformer: Callable[[pa.Table], pa.Table]` applied after the raw webhook payloads are deserialized into row dicts. Delta merge only de-dupes _across_ syncs (on `primary_keys`), not within a single source batch — so when one batch can carry multiple events for the same object (e.g. `customer.created` then `customer.updated`), pass a transformer that keeps only the latest version per id. Reference: `_webhook_table_transformer` in `stripe/stripe.py`, wired via `webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)` in `stripe_source`. It groups rows by `object.id`, keeps the one with the greatest event `created` timestamp, and rebuilds the table shaped like the underlying object (ready to merge on `primary_keys=["id"]`).
