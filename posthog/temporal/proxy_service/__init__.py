from posthog.temporal.proxy_service.create import CreateManagedProxyInputs
from posthog.temporal.proxy_service.delete import DeleteManagedProxyInputs

from posthog.temporal.proxy_service.common import update_proxy_record
from posthog.temporal.proxy_service.create import (
    wait_for_dns_records,
    create_managed_proxy,
    wait_for_certificate,
    CreateManagedProxyWorkflow,
)

from posthog.temporal.proxy_service.delete import delete_proxy_record, delete_managed_proxy, DeleteManagedProxyWorkflow


WORKFLOWS = [CreateManagedProxyWorkflow, DeleteManagedProxyWorkflow]

ACTIVITIES = [
    update_proxy_record,
    wait_for_dns_records,
    create_managed_proxy,
    wait_for_certificate,
    delete_proxy_record,
    delete_managed_proxy,
]
