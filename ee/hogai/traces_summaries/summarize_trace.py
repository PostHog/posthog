import os
import time
from pathlib import Path

import numpy as np
import tiktoken
import structlog
from google import genai
from google.genai.types import GenerateContentConfig

logger = structlog.get_logger(__name__)

FULL_TRACE_SUMMARY_PROMPT = """
- Analyze this conversation between the user and the PostHog AI assistant
- List all pain points, frustrations, and feature limitations the user experienced.
- IMPORTANT: Count only specific issues the user experienced when interacting with the assistant, don't guess or suggest.
- If no issues - return only "No issues found" text, without any additional comments.
- If issues found - provide output as plain English text in a maximum of 10 sentences, while highlighting all the crucial parts.

```
{trace_messages_str}
```
"""


class TraceSummarizer:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.client = self._prepare_client()

    @staticmethod
    def _prepare_client() -> genai.Client:
        api_key = os.getenv("GEMINI_API_KEY")
        return genai.Client(api_key=api_key)

    def generate_trace_summary(self, trace_messages_str: str) -> str:
        message = FULL_TRACE_SUMMARY_PROMPT.format(trace_messages_str=trace_messages_str)
        config_kwargs = {"temperature": 0}  # Not using any system prompt for saving tokens, as should be good enough
        response = self.client.models.generate_content(
            model=self.model_id, contents=message, config=GenerateContentConfig(**config_kwargs)
        )
        response_text = response.text
        if "No issues found" in response_text and response_text != "No issues found":
            logger.info(f"Original 'no issues' text: {response_text}")
            # Ensure to avoid additional comments when no issues found
            return "No issues found"
        return response_text


if __name__ == "__main__":
    stringified_traces_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/output/")
    summarizer = TraceSummarizer(
        model_id="gemini-2.5-flash-lite-preview-09-2025",
    )
    # Iterate over directories in stringified_traces_dir_path
    traces_dirs = list(stringified_traces_dir_path.iterdir())
    traces_processed_count = 0
    # Calculate token count
    token_encoder = tiktoken.encoding_for_model("gpt-4o")
    token_counts: list[int] = []
    # Calculate response times
    response_times_ms: list[int] = []
    # Generate summaries for stringified traces
    for dir_path in traces_dirs:
        if not dir_path.is_dir():
            continue
        trace_id = dir_path.name
        # Get stringified trace
        stringified_messages_file_name = f"{trace_id}_stringified_messages.txt"
        stringified_messages_file_path = dir_path / stringified_messages_file_name
        if not stringified_messages_file_path.exists():
            raise ValueError(
                f"Stringified messages file ({stringified_messages_file_path}) not found for trace {trace_id}"
            )
        # Load stringified trace
        with open(stringified_messages_file_path) as f:
            trace_messages_str = f.read()
        # Check if summary file already exists
        summary_file_path = dir_path / f"{trace_id}_summary.txt"
        if summary_file_path.exists():
            # Check that it's not empty
            with open(summary_file_path) as f:
                summary = f.read()
                if not summary:
                    raise ValueError(f"Summary file ({summary_file_path}) is empty for trace {trace_id}")
            token_counts.append(len(token_encoder.encode(summary)))
            # No need to process again
            traces_processed_count += 1
            continue
        # Summarize trace
        logger.info("*" * 50)
        logger.info(f"Summary for trace {trace_id}:")
        start_time = time.time()
        summary = summarizer.generate_trace_summary(trace_messages_str)  # Call LLM
        end_time = time.time()
        response_time = round((end_time - start_time) * 1000)
        response_times_ms.append(response_time)
        token_counts.append(len(token_encoder.encode(summary)))
        logger.info(summary)
        # TODO: Check for the size of the generated summary, as in some very rare cases the summary could be extremely large (50+ tokens)
        # Store generatedsummary in file
        with open(summary_file_path, "w") as f:
            f.write(summary)
        traces_processed_count += 1
        logger.info(f"Processed {traces_processed_count}/{len(traces_dirs)} traces")
    # Calculate token stats
    token_stats = np.array(token_counts)
    logger.info("Stringified traces summaries token stats:")
    logger.info(f"Average token count: {token_stats.mean()}")
    logger.info(f"Median token count: {np.median(token_stats)}")
    logger.info(f"90th percentile token count: {np.percentile(token_stats, 90)}")
    logger.info(f"95th percentile token count: {np.percentile(token_stats, 95)}")
    logger.info(f"99th percentile token count: {np.percentile(token_stats, 99)}")
    logger.info(f"Min token count: {token_stats.min()}")
    logger.info(f"Max token count: {token_stats.max()}")
    # Calculate response time stats
    response_times_ms_stats = np.array(response_times_ms)
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("Response time stats:")
    logger.info(f"Average response time: {response_times_ms_stats.mean()}")
    logger.info(f"Median response time: {np.median(response_times_ms_stats)}")
    logger.info(f"90th percentile response time: {np.percentile(response_times_ms_stats, 90)}")
    logger.info(f"95th percentile response time: {np.percentile(response_times_ms_stats, 95)}")
    logger.info(f"99th percentile response time: {np.percentile(response_times_ms_stats, 99)}")
    logger.info(f"Min response time: {response_times_ms_stats.min()}")
    logger.info(f"Max response time: {response_times_ms_stats.max()}")
