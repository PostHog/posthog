import type { LoopSchemas } from "@posthog/api-client/loops";
import { Checkbox, Text } from "@posthog/quill";
import { useLoopMcpInstallations } from "../hooks/useLoopMcpInstallations";

interface LoopConnectorFieldsProps {
  connectors: LoopSchemas.LoopConnectors;
  onChange: (connectors: LoopSchemas.LoopConnectors) => void;
  disabled?: boolean;
}

export function LoopConnectorFields({
  connectors,
  onChange,
  disabled,
}: LoopConnectorFieldsProps) {
  const { installations, isLoading } = useLoopMcpInstallations();
  const selected = new Set(connectors.mcp_installation_ids);
  // A disabled installation mounts nothing server-side, so offering it here would
  // promise the loop a connector its runs never get.
  const available = installations.filter((i) => i.is_enabled !== false);
  // Loop runs are unattended, so the backend refuses to hand them a member's
  // personal credentials. Listing those as pickable would silently do nothing.
  const isPersonal = (scope: string | undefined) => scope === "personal";

  const toggle = (id: string, checked: boolean) => {
    const next = new Set(selected);
    if (checked) {
      next.add(id);
    } else {
      next.delete(id);
    }
    onChange({
      ...connectors,
      mcp_installation_ids: available
        .map((i) => i.id)
        .filter((i) => next.has(i)),
    });
  };

  return (
    <div className="flex flex-col gap-2 rounded-(--radius-2) border border-border bg-(--gray-1) p-3">
      <div className="flex flex-col gap-0">
        <Text className="font-medium text-[13px] text-gray-12">Connectors</Text>
        <Text className="text-[12px] text-gray-10">
          MCP servers this loop's runs can use. A run gets only the ones you
          pick here.
        </Text>
      </div>
      {isLoading ? (
        <Text className="text-[12px] text-gray-10">Loading connectors...</Text>
      ) : available.length === 0 ? (
        <Text className="text-[12px] text-gray-10">
          No MCP servers connected yet. Add one in settings to use it here.
        </Text>
      ) : (
        available.map((installation) => (
          <label
            key={installation.id}
            htmlFor={`loop-connector-${installation.id}`}
            className="flex items-center gap-2 text-[13px] text-gray-12"
          >
            <Checkbox
              id={`loop-connector-${installation.id}`}
              checked={selected.has(installation.id)}
              disabled={disabled || isPersonal(installation.scope)}
              onCheckedChange={(checked) =>
                toggle(installation.id, checked === true)
              }
            />
            <span>{installation.display_name || installation.name}</span>
            {isPersonal(installation.scope) ? (
              <Text className="text-[12px] text-gray-10">
                Personal, so a loop can't use it. Turn on "Share with the
                project" for this server to make it available.
              </Text>
            ) : installation.needs_reauth ? (
              <Text className="text-[12px] text-gray-10">
                (needs reconnecting)
              </Text>
            ) : null}
          </label>
        ))
      )}
    </div>
  );
}
