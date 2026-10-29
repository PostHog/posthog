"""Hog function helpers that other products' views call.

A product's presentation layer may import another product's presentation but not its internals, so
the helpers that workflows and messaging views use cross here. Their signatures take models and
return untyped bytecode, so they cannot cross through the facade.
"""

from products.cdp.backend.filters import (
    DATA_WAREHOUSE_SOURCES as DATA_WAREHOUSE_SOURCES,
    compile_filters_expr as compile_filters_expr,
    filter_action_ids as filter_action_ids,
    filter_cohort_ids as filter_cohort_ids,
)
from products.cdp.backend.flag_gated_templates import (
    FLAG_GATED_TEMPLATE_IDS as FLAG_GATED_TEMPLATE_IDS,
    gated_template_enabled as gated_template_enabled,
)
from products.cdp.backend.validation import (
    COHORT_NOT_READY_CODE as COHORT_NOT_READY_CODE,
    build_html_wrap_design as build_html_wrap_design,
    generate_template_bytecode as generate_template_bytecode,
    validate_realtime_cohorts as validate_realtime_cohorts,
)
