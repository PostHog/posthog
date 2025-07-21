from typing import Any

from posthog.schema import SourceConfig, SourceFieldSSHTunnelConfig


def transform_payload(payload: dict[str, Any], source_config: SourceConfig) -> dict[str, Any]:
    """This is a one off special case to handle SSH Tunnel configs. `SSHTunnelAuthConfig`
    has a `type` field which doesn't match how the frontend sends the payload. The
    frontend will send a `selection` field instead.

    No more additions should be made to this function - we should instead work to remove
    the needs for this completely"""

    for field in source_config.fields:
        if isinstance(field, SourceFieldSSHTunnelConfig):
            ssh_tunnel_payload = payload[field.name]

            new_auth_payload = {**ssh_tunnel_payload["auth_type"], "type": ssh_tunnel_payload["auth_type"]["selection"]}
            del new_auth_payload["selection"]

            new_ssh_tunnel_payload = {
                **ssh_tunnel_payload,
                "auth": new_auth_payload,
            }
            del new_ssh_tunnel_payload["auth_type"]

            payload[field.name] = new_ssh_tunnel_payload

    return payload
