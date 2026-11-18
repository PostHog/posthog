"""
Key prefix templates for batch_exports.

Re-exports the renderer behind the S3 key prefix template variables, so the warehouse_sources
file destinations fill a prefix exactly as a batch export does.
"""

from products.batch_exports.backend.temporal.destinations.utils import (
    datetime_template_variables,
    render_key_prefix_template,
)

__all__ = [
    "datetime_template_variables",
    "render_key_prefix_template",
]
