#!/usr/bin/env python3
# ruff: noqa: T201
"""
LLM Benchmark Script

Benchmarks different LLM models on experiment prompts and collects response statistics.
"""

import os
import re
import json
import time
import asyncio
from pathlib import Path
from typing import Any

import yaml
import openai
import tiktoken
import anthropic
from anthropic.types import ThinkingConfigEnabledParam
from dotenv import load_dotenv
from google import genai
from tenacity import retry, retry_if_exception_type, stop_after_attempt

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Configuration, ordering to avoid hitting a single API too often
MODELS = [
    "gemini-3-pro-preview",
    "claude-sonnet-4-5-20250929",
    "gpt-5.2",
    "claude-opus-4-5-20251101",
    "gemini-3-flash-preview",
]

TIMEOUT_SECONDS = 300  # 5 minutes
SEMAPHORE_LIMIT = 10

# Paths
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "benchmark_state.json"
RESULTS_DIR = SCRIPT_DIR / "results"
INPUT_DIR = Path("/Users/woutut/Documents/Code/posthog/playground/identify-objectives-experiments/runs")

# Pre-initialize tiktoken encoder
TIKTOKEN_ENCODER = tiktoken.get_encoding("o200k_base")

# Global state and lock
STATE: dict[str, dict[str, Any]] = {}
STATE_LOCK = asyncio.Lock()


class LLMBenchmarkRetryException(Exception):
    """Raised to trigger tenacity retry after logging error/timeout."""

    pass


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken o3 encoding."""
    return len(TIKTOKEN_ENCODER.encode(text))


def load_state() -> dict[str, dict[str, Any]]:
    """Load state from JSON file or return empty dict."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict[str, dict[str, Any]]) -> None:
    """Save state to JSON file atomically."""
    temp_file = STATE_FILE.with_suffix(".json.tmp")
    with open(temp_file, "w") as f:
        json.dump(state, f, indent=2)
    temp_file.rename(STATE_FILE)


def get_provider(model: str) -> str:
    """Determine provider from model name."""
    if model.startswith("gemini"):
        return "gemini"
    elif model.startswith("claude"):
        return "anthropic"
    elif model.startswith("gpt"):
        return "openai"
    else:
        raise ValueError(f"Unknown model provider for: {model}")


def ensure_state_entry(experiment_id: str, model: str) -> None:
    """Ensure state has an entry for experiment_id + model."""
    if experiment_id not in STATE:
        STATE[experiment_id] = {}
    if model not in STATE[experiment_id]:
        STATE[experiment_id][model] = {
            "success": False,
            "response_time_s": None,
            "input_tokens": None,
            "output_tokens": None,
            "error_count": 0,
            "timeout_count": 0,
        }


def is_already_successful(experiment_id: str, model: str) -> bool:
    """Check if experiment+model combination already succeeded."""
    return STATE.get(experiment_id, {}).get(model, {}).get("success", False)


def save_result_file(experiment_id: str, model: str, response: str) -> None:
    """Save response text to results file."""
    result_dir = RESULTS_DIR / experiment_id
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / f"{model}.txt"
    with open(result_file, "w") as f:
        f.write(response)


def validate_yaml_format(experiment_id: str, model: str) -> bool:
    """Validate that the response is valid YAML format."""
    result_file = RESULTS_DIR / experiment_id / f"{model}.txt"
    if not result_file.exists():
        return False

    text = result_file.read_text().strip()

    if text.startswith("```yaml"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        yaml.safe_load(text)
        return True
    except Exception as err:
        print(f"Invalid YAML format for ee/hogai/llm_testing/results/{experiment_id}/{model}.txt: {err}")
        return False


def validate_results_for_model(model: str, prompts: list[tuple[str, str, str]]) -> None:
    """Validate YAML format for all successful results of a model."""
    for exp_id, _sys_prompt, _prompt in prompts:
        if not STATE.get(exp_id, {}).get(model, {}).get("success", False):
            continue

        is_valid = validate_yaml_format(exp_id, model)
        STATE[exp_id][model]["format_valid"] = is_valid

    save_state(STATE)


async def call_gemini(system_prompt: str, prompt: str, model: str) -> str:
    """Call Gemini API."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=1,  # Recommended by Gemini team for Gemini 3
            thinking_config=genai.types.ThinkingConfig(thinking_level="high"),
        ),
    )
    return response.text


async def call_anthropic(system_prompt: str, prompt: str, model: str) -> str:
    """Call Anthropic API."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=model,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
        temperature=1,
        max_tokens=16384,
        thinking=ThinkingConfigEnabledParam(type="enabled", budget_tokens=8192),
    )
    return response.content[-1].text


async def call_openai(system_prompt: str, prompt: str, model: str) -> str:
    """Call OpenAI API."""
    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.responses.create(
        model=model,
        reasoning={"effort": "high"},
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    return response.output_text


@retry(stop=stop_after_attempt(3), retry=retry_if_exception_type(LLMBenchmarkRetryException))
async def make_request(experiment_id: str, model: str, system_prompt: str, prompt: str) -> None:
    """Make a request to the LLM and update state."""
    provider = get_provider(model)

    async with STATE_LOCK:
        ensure_state_entry(experiment_id, model)

    start_time = time.perf_counter()

    try:
        if provider == "gemini":
            coro = call_gemini(system_prompt, prompt, model)
        elif provider == "anthropic":
            coro = call_anthropic(system_prompt, prompt, model)
        else:
            coro = call_openai(system_prompt, prompt, model)

        response = await asyncio.wait_for(coro, timeout=TIMEOUT_SECONDS)

    except TimeoutError:
        async with STATE_LOCK:
            STATE[experiment_id][model]["timeout_count"] += 1
            save_state(STATE)
        print(f"Timeout for {experiment_id} with {model}")
        raise LLMBenchmarkRetryException(f"Timeout for {experiment_id} with {model}")

    except LLMBenchmarkRetryException:
        raise

    except Exception as e:
        async with STATE_LOCK:
            STATE[experiment_id][model]["error_count"] += 1
            save_state(STATE)
        print(f"Error for {experiment_id} with {model}: {e}")
        raise LLMBenchmarkRetryException(f"Error for {experiment_id} with {model}: {e}")

    elapsed_s = time.perf_counter() - start_time
    input_tokens = count_tokens(system_prompt + prompt)
    output_tokens = count_tokens(response)

    save_result_file(experiment_id, model, response)

    async with STATE_LOCK:
        STATE[experiment_id][model].update(
            {
                "success": True,
                "response_time_s": elapsed_s,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
        save_state(STATE)


def load_prompts() -> list[tuple[str, str, str]]:
    """
    Load and deduplicate prompts from the input directory.

    Returns list of (experiment_id, system_prompt, prompt) tuples.
    """
    prompts_dict: dict[str, tuple[str, str, str]] = {}

    run_dirs = sorted(INPUT_DIR.iterdir())

    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue

        match = re.match(r"^(\d+)_", run_dir.name)
        if not match:
            continue

        experiment_id = match.group(1)

        prompt_files = list(run_dir.glob(f"prompt_{experiment_id}_*.txt"))
        system_prompt_files = list(run_dir.glob(f"system_prompt_{experiment_id}_*.txt"))

        if not prompt_files or not system_prompt_files:
            continue

        prompt_file = prompt_files[0]
        system_prompt_file = system_prompt_files[0]

        if "template" in prompt_file.name:
            continue

        prompt = prompt_file.read_text()
        system_prompt = system_prompt_file.read_text()

        if prompt not in prompts_dict:
            prompts_dict[prompt] = (experiment_id, system_prompt, prompt)

    dedup = list(prompts_dict.values())
    return dedup


async def run_benchmark_for_model(model: str, prompts: list[tuple[str, str, str]]) -> None:
    """Run benchmark for a single model with all prompts."""
    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)

    async def bounded_request(exp_id: str, sys_prompt: str, prompt: str) -> None:
        async with semaphore:
            try:
                await make_request(exp_id, model, sys_prompt, prompt)
            except LLMBenchmarkRetryException:
                pass

    tasks = [
        bounded_request(exp_id, sys_prompt, prompt)
        for exp_id, sys_prompt, prompt in prompts
        if not is_already_successful(exp_id, model)
    ]

    if not tasks:
        print(f"  All prompts already completed for {model}")
    else:
        print(f"  Running {len(tasks)} prompts...")
        await asyncio.gather(*tasks, return_exceptions=True)

    print(f"  Validating YAML format...")
    validate_results_for_model(model, prompts)


def calculate_stats(values: list[float]) -> dict[str, float]:
    """Calculate avg/min/max for a list of values."""
    if not values:
        return {"avg": 0, "min": 0, "max": 0}
    return {
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


def print_stats(state: dict[str, dict[str, Any]], expected_count: int) -> None:
    """Print statistics per model."""
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS")
    print("=" * 80)

    for model in MODELS:
        print(f"\n{model}")
        print("-" * len(model))

        response_times: list[float] = []
        input_tokens_list: list[int] = []
        output_tokens_list: list[int] = []
        total_success = 0
        total_errors = 0
        total_timeouts = 0
        total_requests = 0
        total_format_valid = 0
        total_format_invalid = 0

        for _experiment_id, models_data in state.items():
            if model not in models_data:
                continue

            data = models_data[model]
            total_requests += 1
            total_errors += data.get("error_count", 0)
            total_timeouts += data.get("timeout_count", 0)

            if data.get("success"):
                total_success += 1
                if data.get("response_time_s") is not None:
                    response_times.append(data["response_time_s"])
                if data.get("input_tokens") is not None:
                    input_tokens_list.append(data["input_tokens"])
                if data.get("output_tokens") is not None:
                    output_tokens_list.append(data["output_tokens"])
                if data.get("format_valid") is True:
                    total_format_valid += 1
                elif data.get("format_valid") is False:
                    total_format_invalid += 1

        if total_requests == 0:
            print("  No data")
            continue

        response_stats = calculate_stats(response_times)
        input_stats = calculate_stats([float(t) for t in input_tokens_list])
        output_stats = calculate_stats([float(t) for t in output_tokens_list])

        total_attempts = total_success + total_errors + total_timeouts
        error_rate = (total_errors / total_attempts * 100) if total_attempts > 0 else 0
        timeout_rate = (total_timeouts / total_attempts * 100) if total_attempts > 0 else 0

        total_format_checked = total_format_valid + total_format_invalid
        format_valid_rate = (total_format_valid / total_format_checked * 100) if total_format_checked > 0 else 0
        format_invalid_rate = (total_format_invalid / total_format_checked * 100) if total_format_checked > 0 else 0

        print(f"  Response Time (s):")
        print(f"    avg: {response_stats['avg']:.2f}")
        print(f"    min: {response_stats['min']:.2f}")
        print(f"    max: {response_stats['max']:.2f}")
        print(f"  Input Tokens:")
        print(f"    avg: {input_stats['avg']:.0f}")
        print(f"    min: {input_stats['min']:.0f}")
        print(f"    max: {input_stats['max']:.0f}")
        print(f"  Output Tokens:")
        print(f"    avg: {output_stats['avg']:.0f}")
        print(f"    min: {output_stats['min']:.0f}")
        print(f"    max: {output_stats['max']:.0f}")
        print(f"  Totals:")
        print(f"    expected: {expected_count}")
        # print(f"    successful: {total_success}")
        print(f"    errors: {total_errors} ({error_rate:.2f}%)")
        print(f"    timeouts: {total_timeouts} ({timeout_rate:.2f}%)")
        print(f"    format valid: {total_format_valid} ({format_valid_rate:.2f}%)")
        print(f"    format invalid: {total_format_invalid} ({format_invalid_rate:.2f}%)")


async def main() -> None:
    """Main entry point."""
    global STATE

    print("Loading state...")
    STATE = load_state()

    print("Loading prompts...")
    prompts = load_prompts()
    print(f"Found {len(prompts)} unique prompts")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for model in MODELS:
        print(f"\nTesting {model}...")
        await run_benchmark_for_model(model, prompts)

    print_stats(STATE, len(prompts))


if __name__ == "__main__":
    asyncio.run(main())
