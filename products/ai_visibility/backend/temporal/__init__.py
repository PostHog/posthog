from .activities import (
    combine_calls,
    extract_info_from_url,
    generate_prompts,
    get_topics,
    make_ai_calls,
    mark_run_failed,
    save_results,
    update_progress,
)
from .workflow import AIVisibilityWorkflow

WORKFLOWS = [
    AIVisibilityWorkflow,
]

ACTIVITIES = [
    extract_info_from_url,
    get_topics,
    generate_prompts,
    make_ai_calls,
    combine_calls,
    save_results,
    mark_run_failed,
    update_progress,
]
