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


def _make_name_filesafe(potential_name: str) -> str:
    return potential_name.replace("/", "-")


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
            entities_to_combine_output_path / f"{entity_type}_{_make_name_filesafe(label)}_combination_raw.txt"
        )
        entities_to_combine_output_path_json = (
            entities_to_combine_output_path / f"{entity_type}_{_make_name_filesafe(label)}_combination_raw.json"
        )
        entities_to_combine_output_path_proper = (
            entities_to_combine_output_path / f"{entity_type}_{_make_name_filesafe(label)}_combination.json"
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
    tasks = {}
    async with asyncio.TaskGroup() as tg:
        for product_name, features_to_combine in products_to_features_to_combine_mapping.items():
            tasks[product_name] = tg.create_task(
                _combine_entities(
                    entities_to_combine=set(features_to_combine),
                    entity_type="feature",
                    label=product_name,
                    platform_context=f"{product_name} product",
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

    # Combine the actions per feature
    action_name_to_similar_names_mapping = {}
    tasks = {}
    async with asyncio.TaskGroup() as tg:
        for feature_name, actions_to_combine in features_to_actions_to_combine_mapping.items():
            tasks[feature_name] = tg.create_task(
                _combine_entities(
                    entities_to_combine=set(actions_to_combine),
                    entity_type="action",
                    label=feature_name,
                    platform_context=f"{feature_name} feature",
                    client=client,
                    output_path=base_transcriptions_path,
                )
            )
    for feature_name, task in tasks.items():
        result = task.result()
        if isinstance(result, Exception):
            logger.error(f"Error combining actions for {feature_name}: {result}")
            continue
        action_name_to_similar_names_mapping[feature_name] = result
    print("")

    # Combine everything together
    combined_report = {}
    for product_name, similar_names in product_name_to_similar_names_mapping.items():
        # Find features related to this product
        features_related = []
        for pn in [product_name] + similar_names:
            new_features_related = products_to_features_to_combine_mapping.get(pn)
            if not new_features_related:
                continue
            features_related += new_features_related
        # For each feature - find a unified name for that feature
        base_to_unified_feature_names_mapping = {}
        unified_feature_names = set()
        for base_feature_name in set(features_related):
            unified_groups = feature_name_to_similar_names_mapping.get(product_name)
            if not unified_groups:
                continue
            for unified_feature_name, other_names in unified_groups.items():
                if base_feature_name in other_names:
                    unified_feature_names.add(unified_feature_name)
                    base_to_unified_feature_names_mapping[base_feature_name] = unified_feature_name
                    break
        # For each feature - find actions
        feature_to_actions_mapping = {}
        for base_feature_name in set(features_related):
            action_names = action_name_to_similar_names_mapping.get(base_feature_name)
            if not action_names:
                continue
            # Store all actions under unified mappings
            unified_name_to_map = base_to_unified_feature_names_mapping.get(base_feature_name)
            if not unified_name_to_map:
                continue
            if not feature_to_actions_mapping.get(unified_name_to_map):
                feature_to_actions_mapping[unified_name_to_map] = []
            feature_to_actions_mapping[unified_name_to_map] += [x.capitalize() for x in action_names.keys()]
        # Store into the report
        combined_report[product_name] = {key: list(set(value)) for key, value in feature_to_actions_mapping.items()}
    # Store the report 
    with open(base_transcriptions_path / "combined_report.json", "w") as f:
        json.dump(combined_report, f)
    # Order the features inside each product based on the amount of actions
    for product_name, features_to_actions_mapping in combined_report.items():
        combined_report[product_name] = {k: v for k, v in sorted(features_to_actions_mapping.items(), key=lambda x: len(x[1]), reverse=True)}
    # Order the products based on the amount of features
    combined_report = {k: v for k, v in sorted(combined_report.items(), key=lambda x: len(x[1]), reverse=True)}
    # Store the ordered report
    with open(base_transcriptions_path / "combined_report_ordered.json", "w") as f:
        json.dump(combined_report, f)
    print("")


if __name__ == "__main__":
    asyncio.run(combine_everything())
