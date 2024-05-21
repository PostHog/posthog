from posthog.temporal.proxy_service.create import CreateHostedProxyInputs
from posthog.temporal.proxy_service.delete import DeleteHostedProxyInputs

from posthog.temporal.proxy_service.common import update_proxy_record
from posthog.temporal.proxy_service.create import (
    wait_for_dns_records,
    create_hosted_proxy,
    wait_for_certificate,
    CreateHostedProxyWorkflow,
)

from posthog.temporal.proxy_service.delete import delete_proxy_record, delete_hosted_proxy, DeleteHostedProxyWorkflow


WORKFLOWS = [CreateHostedProxyWorkflow, DeleteHostedProxyWorkflow]

ACTIVITIES = [
    update_proxy_record,
    wait_for_dns_records,
    create_hosted_proxy,
    wait_for_certificate,
    delete_proxy_record,
    delete_hosted_proxy,
]
