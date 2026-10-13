"""
Facade re-exports for the annotation context AI surfaces embed in their prompts.

An insight summary, a dashboard summary and a subscription snapshot each resolve their own
date window and then ask for the annotations in it. Callers outside this product import the
two helpers from here rather than reaching the internal ``annotation_context`` module.
"""

from products.annotations.backend.api.annotation_context import (
    build_annotations_block,
    resolve_query_date_range,
    resolve_snapshot_date_range,
)

__all__ = ["build_annotations_block", "resolve_query_date_range", "resolve_snapshot_date_range"]
