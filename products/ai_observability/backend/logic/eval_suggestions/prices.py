"""List prices of the models eval suggestions calls or estimates for, per token."""

from posthog.dataclasses import frozen


@frozen
class ModelPrice:
    input_per_token: float
    output_per_token: float


# ponytail: list prices of each provider's default judge model and of the review models, read for estimates and the
# run budget only. Model prices live in the Node ingestion package, which the Python image does not ship; move this
# to a shared file when a caller outside eval suggestions needs prices. A test keeps every provider default priced here.
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5-mini": ModelPrice(input_per_token=0.25e-6, output_per_token=2e-6),
    "claude-haiku-4-5": ModelPrice(input_per_token=1e-6, output_per_token=5e-6),
    "claude-opus-5-5": ModelPrice(input_per_token=4e-6, output_per_token=20e-6),
    "gemini-2.5-flash": ModelPrice(input_per_token=0.3e-6, output_per_token=2.5e-6),
}
