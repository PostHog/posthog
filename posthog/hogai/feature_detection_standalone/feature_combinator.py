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


# "PostHog platform"
async def _combine_entities(
    entities_to_combine: set[str],
    entity_type: str,
    label: str,
    platform_context: str,
    client: openai.AsyncOpenAI,
    output_path: Path,
) -> dict[str, list[str]] | Exception:
    try:
        entities_to_combine_output_path = output_path / "combination"
        # Ensure to create the directory
        entities_to_combine_output_path.mkdir(parents=True, exist_ok=True)
        entities_to_combine_output_path_raw = (
            entities_to_combine_output_path / f"{entity_type}_{label}_combination_raw.txt"
        )
        entities_to_combine_output_path_json = (
            entities_to_combine_output_path / f"{entity_type}_{label}_combination_raw.json"
        )
        entities_to_combine_output_path_proper = (
            entities_to_combine_output_path / f"{entity_type}_{label}_combination.json"
        )
        # If files exists already - skip
        if (
            entities_to_combine_output_path_raw.exists()
            and entities_to_combine_output_path_json.exists()
            and entities_to_combine_output_path_proper.exists()
        ):
            with open(entities_to_combine_output_path_proper, "r") as f:
                return json.load(f)
        entities_to_combine_ordered = list(entities_to_combine)
        entities_to_combine_ordered_str = "\n".join(
            [f"{i}. {entity_name}" for i, entity_name in enumerate(entities_to_combine_ordered)]
        )
        combination_prompt = BASE_FEATURE_COMBINATION_PROMPT.format(
            features_to_combine_ordered=entities_to_combine_ordered_str, platform_context=platform_context
        )
        response = await client.responses.create(
            input=combination_prompt,
            model="o3",
            reasoning={"effort": "medium"},
        )
        # Load markdown to JSON
        with open(entities_to_combine_output_path_raw, "w") as f:
            f.write(response.output_text)
        dictified_response = markdown_to_json.dictify(response.output_text)
        with open(entities_to_combine_output_path_json, "w") as f:
            json.dump(dictified_response, f)
        # Create a product to synonyms naming mapping
        entity_name_to_similar_names_mapping = {}
        entity_mapping_data = dictified_response["root"][0]
        for i in range(len(entity_mapping_data)):
            entity_data = entity_mapping_data[i]
            if not isinstance(entity_data, str):
                continue
            if i + 1 > len(entity_mapping_data):
                continue
            next_entity_data = entity_mapping_data[i + 1]
            if not isinstance(next_entity_data, list):
                continue
            entity_name_to_similar_names_mapping[entity_data] = [
                entities_to_combine_ordered[int(x.strip())] for x in next_entity_data
            ]
        with open(entities_to_combine_output_path_proper, "w") as f:
            json.dump(entity_name_to_similar_names_mapping, f)
        return entity_name_to_similar_names_mapping
    except Exception as e:
        logger.error(f"Error combining entities for {entity_type} {label}: {e}")
        # Let handler catch the exception
        return e


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
    product_combination_result = await _combine_entities(
        entities_to_combine=set(products_to_combine),
        entity_type="product",
        label="",
        platform_context="PostHog platform",
        client=client,
        output_path=base_transcriptions_path,
    )
    if isinstance(product_combination_result, Exception):
        logger.error(f"Error combining products: {product_combination_result}")
        return
    product_name_to_similar_names_mapping: dict[str, list[str]] = product_combination_result

    # Combine the features per product
    feature_name_to_similar_names_mapping = {}
    for product_name, features_to_combine in products_to_features_to_combine_mapping.items():
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            tasks[product_name] = tg.create_task(
                _combine_entities(
                    entities_to_combine=set(features_to_combine),
                    entity_type="feature",
                    label=product_name,
                    platform_context=product_name,
                    client=client,
                    output_path=base_transcriptions_path,
                )
            )
    for product_name, task in tasks.items():
        result = task.result()
        if isinstance(result, Exception):
            logger.error(f"Error combining features for {product_name}: {result}")
            continue
        feature_name_to_similar_names_mapping[product_name] = result
    print("")


if __name__ == "__main__":
    asyncio.run(combine_everything())
