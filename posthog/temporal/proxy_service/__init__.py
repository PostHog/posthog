# ruff: noqa: F401 intentionally not using these

from posthog.temporal.proxy_service.common import activity_capture_event, activity_update_proxy_record
from posthog.temporal.proxy_service.create import (
    CreateManagedProxyInputs,
    CreateManagedProxyWorkflow,
    create_cloudflare_custom_hostname,
    create_cloudflare_worker_route,
    create_managed_proxy,
    schedule_monitor_job,
    wait_for_certificate,
    wait_for_cloudflare_certificate,
    wait_for_dns_records,
)
from posthog.temporal.proxy_service.delete import (
    DeleteManagedProxyInputs,
    DeleteManagedProxyWorkflow,
    delete_cloudflare_proxy,
    delete_managed_proxy,
    delete_proxy_record,
)
from posthog.temporal.proxy_service.monitor import (
    MonitorManagedProxyInputs,
    MonitorManagedProxyWorkflow,
    check_certificate_status,
    check_dns,
    check_proxy_is_live,
    cleanup_monitor_job,
)

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
    # Cloudflare for SaaS activities
    create_cloudflare_custom_hostname,
    create_cloudflare_worker_route,
    wait_for_cloudflare_certificate,
    delete_cloudflare_proxy,
]
