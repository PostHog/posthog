from posthog.temporal.proxy_service.create import CreateManagedProxyInputs
from posthog.temporal.proxy_service.delete import DeleteManagedProxyInputs
from posthog.temporal.proxy_service.monitor import MonitorManagedProxyInputs

from posthog.temporal.proxy_service.common import (
    activity_update_proxy_record,
    activity_capture_event,
)

from posthog.temporal.proxy_service.create import (
    wait_for_dns_records,
    create_managed_proxy,
    wait_for_certificate,
    CreateManagedProxyWorkflow,
    schedule_monitor_job,
)
from posthog.temporal.proxy_service.monitor import (
    check_certificate_status,
    check_dns,
    check_proxy_is_live,
    MonitorManagedProxyWorkflow,
    cleanup_monitor_job,
)

from posthog.temporal.proxy_service.delete import delete_proxy_record, delete_managed_proxy, DeleteManagedProxyWorkflow


WORKFLOWS = [CreateManagedProxyWorkflow, DeleteManagedProxyWorkflow, MonitorManagedProxyWorkflow]

ACTIVITIES = [
    activity_update_proxy_record,
    wait_for_dns_records,
    create_managed_proxy,
    wait_for_certificate,
    delete_proxy_record,
    delete_managed_proxy,
    check_certificate_status,
    check_dns,
    check_proxy_is_live,
    activity_capture_event,
    schedule_monitor_job,
    cleanup_monitor_job,
]
