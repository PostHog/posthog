"""Temporal workflows and activities this product registers on the evals queue, which is the
only worker image that carries the sentiment model."""

from products.aeo.backend.temporal.brand_sentiment import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]
