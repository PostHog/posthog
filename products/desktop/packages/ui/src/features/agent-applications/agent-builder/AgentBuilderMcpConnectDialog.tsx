import { AddCustomServerDialog } from "@posthog/ui/features/mcp-server-manager/AddCustomServerDialog";
import type { CustomServerInput } from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import type { PendingMcpConnect } from "./agentBuilderStore";

/**
 * Modal for the agent builder's `connect_mcp` punch-out. The agent parks its
 * turn and supplies a prefilled name/url; the user reviews + completes the
 * connect (OAuth / api key) here — the agent never sees the credentials. On
 * success the connection is written onto the target agent's spec and the
 * session woken. Thin wrapper over {@link AddCustomServerDialog} with
 * punch-out-specific copy and the agent's prefilled values.
 */
export function AgentBuilderMcpConnectDialog({
  pending,
  busy,
  onSubmit,
  onCancel,
}: {
  pending: PendingMcpConnect | null;
  busy: boolean;
  onSubmit: (values: CustomServerInput) => void;
  onCancel: () => void;
}) {
  return (
    <AddCustomServerDialog
      open={!!pending}
      pending={busy}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      onSubmit={onSubmit}
      initialValues={
        pending ? { name: pending.name, url: pending.url } : undefined
      }
      title="Connect an MCP server"
      description={
        pending?.purpose ??
        "Connect a server for this agent. You complete the sign-in — the agent builder never sees your credentials."
      }
    />
  );
}
