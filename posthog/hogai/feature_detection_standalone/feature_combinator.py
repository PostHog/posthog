import asyncio
import json
import os
from pathlib import Path
from google.genai.types import GenerateContentConfig, ThinkingConfig
import markdown_to_json
from google.genai import Client
import structlog
from tqdm.asyncio import tqdm
import openai

logger = structlog.get_logger(__name__)

FEATURE_DETECTION_MODEL_ID = "gemini-2.5-flash-preview-09-2025"

BASE_FEATURE_COMBINATION_PROMPT = """
<task>
- Combine the list of feature names and synonyms into unified feature names list for the {platform_context}
- For example: "Google Mail", "Gmail", "gmail mail", "Google Email" should all be combined into "Google Mail"
- Return as a markdown with the final feature name and indexes of the combined feature names
- Don't provide any comments, only return the result
</task>

<output_format_example>
- Google Mail
  * 10
  * 5
  * 4
  ...
</output_format_example>

<feature_names_input>
{features_to_combine_ordered}
</feature_names_input>
"""


def _get_async_client() -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def _combine_products(
    products_to_combine: set[str], client: openai.AsyncOpenAI, output_path: Path
) -> dict[str, list[str]]:
    products_to_combine_output_path = output_path / "combination"
    # Ensure to create the directory
    products_to_combine_output_path.mkdir(parents=True, exist_ok=True)
    products_to_combine_output_path_raw = products_to_combine_output_path / "products_combination_raw.txt"
    products_to_combine_output_path_json = products_to_combine_output_path / "products_combination_raw.json"
    products_to_combine_output_path_proper = products_to_combine_output_path / "products_combination.json"
    # If files exists already - skip
    if (
        products_to_combine_output_path_raw.exists()
        and products_to_combine_output_path_json.exists()
        and products_to_combine_output_path_proper.exists()
    ):
        with open(products_to_combine_output_path_proper, "r") as f:
            return json.load(f)
    products_to_combine_ordered = list(products_to_combine)
    products_to_combine_ordered_str = "\n".join(
        [f"{i}. {product_name}" for i, product_name in enumerate(products_to_combine_ordered)]
    )
    combination_prompt = BASE_FEATURE_COMBINATION_PROMPT.format(
        features_to_combine_ordered=products_to_combine_ordered_str, platform_context="PostHog platform"
    )
    response = await client.responses.create(
        input=combination_prompt,
        model="o3",
        reasoning={"effort": "medium"},
    )
    # Load markdown to JSON
    with open(products_to_combine_output_path_raw, "w") as f:
        f.write(response.output_text)
    dictified_response = markdown_to_json.dictify(response.output_text)
    with open(products_to_combine_output_path_json, "w") as f:
        json.dump(dictified_response, f)
    # Create a product to synonyms naming mapping
    product_name_to_similar_names_mapping = {}
    product_mapping_data = dictified_response["root"][0]
    for i in range(len(product_mapping_data)):
        product_data = product_mapping_data[i]
        if not isinstance(product_data, str):
            continue
        if i + 1 > len(product_mapping_data):
            continue
        next_product_data = product_mapping_data[i + 1]
        if not isinstance(next_product_data, list):
            continue
        product_name_to_similar_names_mapping[product_data] = [
            products_to_combine_ordered[int(x.strip())] for x in next_product_data
        ]
    with open(products_to_combine_output_path_proper, "w") as f:
        json.dump(product_name_to_similar_names_mapping, f)
    return product_name_to_similar_names_mapping


async def combine_everything():
    client = _get_async_client()
    base_transcriptions_path = Path("/Users/woutut/Documents/Code/posthog/playground/feature_detection/transcription/")
    # Iterate over session folders and pick feature detection files (starts with `feature-detection_` and have `json` extension)
    input_session_id_to_feature_detection = {}
    # Pick the names
    products_to_combine = []
    features_to_combine = []
    products_to_features_to_combine_mapping = {}
    features_to_actions_to_combine_mapping = {}
    for session_folder in base_transcriptions_path.iterdir():
        if not session_folder.is_dir():
            continue
        # Iterate over files in the session folder
        for file in session_folder.iterdir():
            if not file.is_file():
                continue
            if not file.name.startswith("feature-detection_") or not file.name.endswith(".json"):
                continue
            with open(file, "r") as f:
                feature_detection = json.load(f)["root"]
            session_id = session_folder.name
            input_session_id_to_feature_detection[session_id] = feature_detection
            # Pick the products
            for i, product_data in enumerate(feature_detection):
                if not isinstance(product_data, list):
                    continue
                for product_part in product_data:
                    if isinstance(product_part, str):
                        # String - means product name
                        products_to_combine.append(product_part)
                    elif isinstance(product_part, list):
                        # List - means features
                        for feature_part in product_part:
                            if isinstance(feature_part, str):
                                # String - means feature name
                                last_product_name = products_to_combine[-1]
                                if products_to_features_to_combine_mapping.get(last_product_name) is None:
                                    products_to_features_to_combine_mapping[last_product_name] = []
                                products_to_features_to_combine_mapping[last_product_name].append(feature_part)
                                features_to_combine.append(feature_part)
                            elif isinstance(feature_part, list):
                                # List - means actions
                                for action_part in feature_part:
                                    if isinstance(action_part, str):
                                        # String - means action name
                                        last_feature_name = features_to_combine[-1]
                                        if features_to_actions_to_combine_mapping.get(last_feature_name) is None:
                                            features_to_actions_to_combine_mapping[last_feature_name] = []
                                        features_to_actions_to_combine_mapping[last_feature_name].append(action_part)

    # Combine the products
    product_name_to_similar_names_mapping = await _combine_products(
        set(products_to_combine), client, base_transcriptions_path
    )

    # Combine the features


if __name__ == "__main__":
    asyncio.run(combine_everything())
