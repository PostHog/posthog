import json
import datetime as dt

import pytest

import pyarrow as pa

from posthog.temporal.common.arrow_pipeline.transformer import JSONLStreamTransformer

from products.batch_exports.backend.temporal.pipeline.events import INSERTED_AT_COLUMN, strip_web_vitals_nested_elements

DEEPLY_NESTED = json.loads("[" * 256 + "]" * 256)


@pytest.mark.parametrize(
    "event, attribution, expected_attribution",
    [
        ("$web_vitals", {"interactionTargetElement": DEEPLY_NESTED, "other": 1}, {"other": 1}),
        # The stdlib json fallback keeps the record unchanged.
        ("$pageview", {"interactionTargetElement": DEEPLY_NESTED, "other": 1}, None),
        ("$web_vitals", {"nested": DEEPLY_NESTED}, None),
    ],
)
@pytest.mark.asyncio
async def test_jsonl_stream_transformer_strips_web_vitals_nested_elements(event, attribution, expected_attribution):
    record_batch = pa.RecordBatch.from_pylist(
        [
            {
                "event": event,
                "properties": {"$web_vitals_INP_event": {"attribution": attribution}},
                INSERTED_AT_COLUMN: dt.datetime.fromtimestamp(0),
            }
        ]
    )
    expected = record_batch.to_pylist()[0]
    del expected[INSERTED_AT_COLUMN]
    if expected_attribution is not None:
        expected["properties"]["$web_vitals_INP_event"]["attribution"] = expected_attribution

    transformer = JSONLStreamTransformer(
        exclude_columns=(INSERTED_AT_COLUMN,),
        max_workers=1,
        on_recursion_limit=strip_web_vitals_nested_elements,
    )

    async def record_batches():
        yield record_batch

    data = b"".join([chunk.data async for chunk in transformer.iter(record_batches())])

    assert json.loads(data) == expected
