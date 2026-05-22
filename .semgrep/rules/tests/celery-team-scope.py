# Test cases for celery-team-scope semgrep rule

from celery import shared_task

from posthog.models.feature_flag import FeatureFlag
from posthog.models.scoping import with_team_scope


# ruleid: celery-task-team-scope-audit
@shared_task
def bad_task_no_scoping():
    # This should be flagged - no team scoping
    flags = FeatureFlag.objects.all()
    return flags


# ruleid: celery-task-team-scope-audit
@shared_task(ignore_result=True)
def bad_task_with_filter():
    # This should be flagged - no team scoping
    flags = FeatureFlag.objects.filter(active=True)
    return flags


# ok: celery-task-team-scope-audit
@shared_task
@with_team_scope()
def good_task_with_decorator(team_id: int):
    # This is OK - has @with_team_scope decorator
    flags = FeatureFlag.objects.all()
    return flags


# ok: celery-task-team-scope-audit
@shared_task
def good_task_with_unscoped():
    # This is OK - explicitly unscoped
    flags = FeatureFlag.objects.unscoped().all()
    return flags


# ok: celery-task-team-scope-audit
@shared_task
def good_task_with_unscoped_filter():
    # This is OK - explicitly unscoped
    flags = FeatureFlag.objects.unscoped().filter(active=True)
    return flags


# Not a celery task - should not be flagged
def regular_function():
    flags = FeatureFlag.objects.all()
    return flags
