import type {
  McpGatewayServer,
  McpResolvedToolPolicy,
  McpServiceAccount,
} from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GiveAccessDialog } from "./GiveAccessDialog";

Element.prototype.scrollIntoView = vi.fn();

const server: McpGatewayServer = {
  id: "server-1",
  name: "Notion",
  url: "https://mcp.notion.com",
  description: "Notion MCP",
  category: "productivity",
  is_team_enabled: true,
  icon_key: "notion",
  docs_url: "",
  template_id: "template-1",
  template_auth_type: null,
  tool_count: 0,
  connections: [],
  your_connection: null,
  agents: [],
  revoked_user_ids: [],
  is_revoked_for_you: false,
  created_by: null,
  created_at: "2026-07-23T12:00:00Z",
  updated_at: "2026-07-23T12:00:00Z",
};

const account: McpServiceAccount = {
  id: "agent-1",
  name: "Support agent",
  description: "",
  handle: "posthog-support",
  status: "active",
  token_mask: "",
  server_ids: [],
  last_active_at: null,
  created_at: "2026-07-23T12:00:00Z",
  updated_at: "2026-07-23T12:00:00Z",
};

const toolPolicy: McpResolvedToolPolicy = {
  tool_name: "search_pages",
  description: "",
  input_schema: {},
  policy_state: "needs_approval",
  team_state: null,
  locked: false,
  decided_by: "default",
  rule_name: "",
  rule_description: "",
};

const secondAccount: McpServiceAccount = {
  ...account,
  id: "agent-2",
  name: "Docs agent",
  handle: "posthog-docs",
};

describe("GiveAccessDialog", () => {
  it("only offers allow or block when configuring an agent", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <GiveAccessDialog
          open
          server={server}
          accounts={[account]}
          toolPolicies={[toolPolicy]}
          pending={false}
          onClose={vi.fn()}
          onGrant={vi.fn()}
        />
      </Theme>,
    );

    screen.getByRole("combobox").focus();
    await user.keyboard("{ArrowDown}{Enter}");

    expect(
      screen.getByRole("radio", { name: "Always Allow" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("radio", { name: "Needs Approval" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Blocked" })).toBeInTheDocument();
  });

  it("resets the agent and policy overrides when the dialog closes", async () => {
    const user = userEvent.setup();
    const view = render(
      <Theme>
        <GiveAccessDialog
          open
          server={server}
          accounts={[account]}
          toolPolicies={[toolPolicy]}
          pending={false}
          onClose={vi.fn()}
          onGrant={vi.fn()}
        />
      </Theme>,
    );

    screen.getByRole("combobox").focus();
    await user.keyboard("{ArrowDown}{Enter}");
    await user.click(screen.getByRole("radio", { name: "Blocked" }));
    expect(screen.getByRole("radio", { name: "Blocked" })).toBeChecked();

    const rerenderDialog = (open: boolean) =>
      view.rerender(
        <Theme>
          <GiveAccessDialog
            open={open}
            server={server}
            accounts={[account]}
            toolPolicies={[toolPolicy]}
            pending={false}
            onClose={vi.fn()}
            onGrant={vi.fn()}
          />
        </Theme>,
      );
    rerenderDialog(false);
    rerenderDialog(true);

    expect(screen.getByRole("combobox")).toHaveTextContent("Choose an agent…");
    expect(screen.queryAllByRole("radio")).toHaveLength(0);

    screen.getByRole("combobox").focus();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByRole("radio", { name: "Blocked" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Always Allow" })).toBeChecked();
  });

  it("does not carry one agent's policy overrides over to another agent", async () => {
    const user = userEvent.setup();
    const onGrant = vi.fn();
    render(
      <Theme>
        <GiveAccessDialog
          open
          server={server}
          accounts={[account, secondAccount]}
          toolPolicies={[toolPolicy]}
          pending={false}
          onClose={vi.fn()}
          onGrant={onGrant}
        />
      </Theme>,
    );

    screen.getByRole("combobox").focus();
    await user.keyboard("{ArrowDown}{Enter}");
    await user.click(screen.getByRole("radio", { name: "Blocked" }));
    expect(screen.getByRole("radio", { name: "Blocked" })).toBeChecked();

    screen.getByRole("combobox").focus();
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(screen.getByRole("radio", { name: "Blocked" })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Share access" }));
    expect(onGrant).toHaveBeenCalledWith("agent-2", [
      { tool_name: "search_pages", policy_state: "approved" },
    ]);
  });

  it("shows a spinner and prevents closing while access is being shared", () => {
    const onClose = vi.fn();
    render(
      <Theme>
        <GiveAccessDialog
          open
          server={server}
          accounts={[account]}
          toolPolicies={[]}
          pending
          onClose={onClose}
          onGrant={vi.fn()}
        />
      </Theme>,
    );

    const shareButton = screen.getByRole("button", { name: "Share access" });
    expect(shareButton).toBeDisabled();
    expect(shareButton.querySelector(".rt-Spinner")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
