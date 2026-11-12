"""Temporal workflows and activities this product registers on the AEO queue. Its worker runs the
LLM analytics image, the only one that carries the sentiment model."""

from products.aeo.backend.temporal.brand_sentiment import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]
