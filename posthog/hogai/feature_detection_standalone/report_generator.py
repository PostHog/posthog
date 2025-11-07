import asyncio
import json
import os
from pathlib import Path
import openai


BASE_REPORT_GENERATOR_PROMPT = """
<task>
- I have a feature research report in JSON format, that shows what products -> features (within a product) -> functionality (within features) users used
- The data can be repetitive, as it's extracted from hundreds of session
- I need you to clean it up and return to me in markdown format:

```
- Product
  - Feature
    - functionality
```

- The goal is to pick products, features per product, and functionality per feature, avoiding duplicates, and keeping only ones that properly demonstate what features the product has
- Keep as many products, features, and functionalities as possible, while avoiding duplicates
- Avoid including generic entities like "Navigation", "Settings", "Configuration", etc., the goal should be product-specific
</task>

<feature_detection_report_input>
{feature_detection_report_input}
</feature_detection_report_input>
"""


def _get_async_client() -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def generate_feature_detection_report() -> str:
    client = _get_async_client()
    base_transcriptions_path = Path("/Users/woutut/Documents/Code/posthog/playground/feature_detection/transcription/")
    input_report_path = base_transcriptions_path / "combined_report.json"
    with open(input_report_path, "r") as f:
        input_report = json.load(f)
    prompt = BASE_REPORT_GENERATOR_PROMPT.format(feature_detection_report_input=json.dumps(input_report))
    response = await client.responses.create(
        input=prompt,
        model="gpt-5",
        reasoning={"effort": "high"},
    )
    with open(base_transcriptions_path / "feature_detection_report.md", "w") as f:
        f.write(response.output_text)
    return None

if __name__ == "__main__":
    asyncio.run(generate_feature_detection_report())