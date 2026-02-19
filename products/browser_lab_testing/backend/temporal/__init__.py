from .run_browser_lab_test.activities import run_browser_lab_test_activity
from .run_browser_lab_test.workflow import RunBrowserLabTestWorkflow

WORKFLOWS = [
    RunBrowserLabTestWorkflow,
]

ACTIVITIES = [
    run_browser_lab_test_activity,
]
