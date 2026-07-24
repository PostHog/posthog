import type { McpAuthType } from "@posthog/api-client/posthog-client";
import { AddCustomServerForm } from "@posthog/ui/features/mcp-server-manager/AddCustomServerForm";
import type { CustomServerInput } from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { Dialog } from "@radix-ui/themes";

/**
 * Modal wrapper around {@link AddCustomServerForm}. The form is a full
 * multi-field form, so connecting a server pops out a dialog rather than
 * expanding inline. Radix unmounts the content on close, so each open starts
 * from a fresh form (reset to `initialValues`). Used by the agent-config MCP
 * sections and the agent builder's `connect_mcp` punch-out.
 */
export function AddCustomServerDialog({
  open,
  pending,
  onOpenChange,
  onSubmit,
  initialValues,
  title = "Add MCP server",
  description = "Connect a custom MCP server by URL. Tools appear in your agent once the connection is verified.",
}: {
  open: boolean;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: CustomServerInput) => void;
  initialValues?: {
    name?: string;
    url?: string;
    description?: string;
    auth_type?: McpAuthType;
  };
  title?: string;
  description?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="520px" size="3">
        <Dialog.Title className="text-base">{title}</Dialog.Title>
        <Dialog.Description className="mb-4 text-sm" color="gray">
          {description}
        </Dialog.Description>
        <AddCustomServerForm
          pending={pending}
          hideHeader
          initialValues={initialValues}
          onSubmit={onSubmit}
          onBack={() => onOpenChange(false)}
        />
      </Dialog.Content>
    </Dialog.Root>
  );
}
