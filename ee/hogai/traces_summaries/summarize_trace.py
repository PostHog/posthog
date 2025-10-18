import os
from pathlib import Path
from google import genai
from google.genai.types import GenerateContentConfig
import tiktoken
import numpy as np

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

TEST_TRACE = """
human: whats my project id?

ai: Your project ID is 69319.

human: and my POSTHOG_MANAGEMENT_KEY

ai: I cannot access or display your POSTHOG_MANAGEMENT_KEY directly for security reasons. If you need to find or generate your management key, you can do this in your project settings within the PostHog app.

Here’s how to find it:

1. Go to your project settings in PostHog.
2. Look for the section labeled “API keys” or “Project API keys.”
3. You’ll find your management key there, or you can generate a new one if needed.

If you need step-by-step guidance, let me know and I can walk you through the process.
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
        if "No issues found" in response_text:
            print("Original 'no issues' text:", response_text)
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
        with open(stringified_messages_file_path, "r") as f:
            trace_messages_str = f.read()
        # Check if summary file already exists
        summary_file_path = dir_path / f"{trace_id}_summary.txt"
        if summary_file_path.exists():
            # Check that it's not empty
            with open(summary_file_path, "r") as f:
                summary = f.read()
                if not summary:
                    raise ValueError(f"Summary file ({summary_file_path}) is empty for trace {trace_id}")
            token_counts.append(len(token_encoder.encode(summary)))
            # No need to process again
            traces_processed_count += 1
            continue
        # Summarize trace
        print("*" * 50)
        print(f"Summary for trace {trace_id}:")
        summary = summarizer.generate_trace_summary(trace_messages_str)
        token_counts.append(len(token_encoder.encode(summary)))
        print(summary)
        # Store generatedsummary in file
        with open(summary_file_path, "w") as f:
            f.write(summary)
        traces_processed_count += 1
        print(f"Processed {traces_processed_count}/{len(traces_dirs)} traces")
    # Calculate token stats
    token_stats = np.array(token_counts)
    print("Stringified traces summaries token stats:")
    print(f"Average token count: {token_stats.mean()}")
    print(f"Median token count: {np.median(token_stats)}")
    print(f"90th percentile token count: {np.percentile(token_stats, 90)}")
    print(f"95th percentile token count: {np.percentile(token_stats, 95)}")
    print(f"99th percentile token count: {np.percentile(token_stats, 99)}")
    print(f"Min token count: {token_stats.min()}")
    print(f"Max token count: {token_stats.max()}")
