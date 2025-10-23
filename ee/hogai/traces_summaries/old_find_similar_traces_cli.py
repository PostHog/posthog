import csv
import json
import argparse
from pathlib import Path

import structlog
from search_summaries_embeddings_cli import EmbeddingSearcher
from stringify_trace import TraceMessagesStringifier
from summarize_trace import TraceSummarizer

logger = structlog.get_logger(__name__)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace_id", type=str, required=True, help="Trace ID")
    parser.add_argument("--top", type=int, required=False, default=5, help="Number of top similar traces to return")
    args = parser.parse_args()
    # Load data
    trace_id = args.trace_id
    csv_trace_file_path = Path(
        f"/Users/woutut/Documents/Code/posthog/playground/traces-summarization/test_{trace_id}.csv"
    )
    input_state = output_state = None
    with open(csv_trace_file_path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            input_state_raw = row[-3]
            input_state = json.loads(input_state_raw)
            output_state_raw = row[-2]
            output_state = json.loads(output_state_raw)
            break
    # Stringify trace
    stringifier = TraceMessagesStringifier(
        trace_id=trace_id,
        input_state=input_state,
        output_state=output_state,
    )
    stringified_messages = stringifier.stringify_trace_messages()
    stringified_messages_str = "\n\n".join(stringified_messages)
    # Generate summary for the trace
    summarizer = TraceSummarizer(model_id="gemini-2.5-flash-lite-preview-09-2025")
    trace_summary = summarizer.generate_trace_summary(trace_messages_str=stringified_messages_str)
    logger.info(f"Input trace summary ({trace_id}):\n{trace_summary}")
    logger.info("-" * 50)
    logger.info("-" * 50)
    logger.info("-" * 50)
    # Find similar traces
    similar_traces = EmbeddingSearcher.prepare_input_data(question=trace_summary, top=args.top)
    # print(similar_traces)
