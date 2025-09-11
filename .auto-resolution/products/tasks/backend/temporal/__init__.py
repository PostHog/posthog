from .activities import (
    ai_agent_work_activity,
    get_task_details_activity,
    process_task_moved_to_todo_activity,
    update_issue_github_info_activity,
    update_issue_status_activity,
)
from .github_activities import (
    cleanup_repo_activity,
    clone_repo_and_create_branch_activity,
    commit_changes_activity,
    commit_local_changes_activity,
    create_branch_activity,
    create_pr_activity,
    validate_github_integration_activity,
)
from .workflows import TaskProcessingWorkflow

WORKFLOWS = [
    TaskProcessingWorkflow,
]

ACTIVITIES = [
    process_task_moved_to_todo_activity,
    update_issue_status_activity,
    ai_agent_work_activity,
    get_task_details_activity,
    update_issue_github_info_activity,
    clone_repo_and_create_branch_activity,
    cleanup_repo_activity,
    validate_github_integration_activity,
    create_branch_activity,
    create_pr_activity,
    commit_changes_activity,
    commit_local_changes_activity,
]
