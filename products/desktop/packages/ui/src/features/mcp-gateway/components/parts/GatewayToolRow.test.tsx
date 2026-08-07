import type { McpResolvedToolPolicy } from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GatewayToolRow } from "./GatewayToolRow";

const policy: McpResolvedToolPolicy = {
  tool_name: "search_items",
  description:
    "Search the catalog for matching items.\n\n- Match by title\n- Match by description",
  input_schema: {
    type: "object",
    properties: {
      query: { type: "string" },
    },
    required: ["query"],
  },
  policy_state: "needs_approval",
  team_state: null,
  locked: false,
  decided_by: "default",
  rule_name: "",
  rule_description: "",
};

describe("GatewayToolRow", () => {
  it("shows separate description and input schema sections when expanded", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Theme>
        <GatewayToolRow policy={policy} editable onChange={vi.fn()} />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: /search_items/i }));

    expect(screen.getByText("Description")).toBeInTheDocument();
    expect(screen.getByText("Input schema")).toBeInTheDocument();
    expect(container.querySelector(".whitespace-pre-wrap")).toHaveTextContent(
      "Search the catalog for matching items. - Match by title - Match by description",
    );
    expect(container.querySelector("pre")?.textContent).toBe(
      JSON.stringify(policy.input_schema, null, 2),
    );
  });

  it("shows the team-admin badge and only disables states above the ceiling", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Theme>
        <GatewayToolRow
          policy={{
            ...policy,
            policy_state: "needs_approval",
            team_state: "needs_approval",
            decided_by: "team",
          }}
          editable
          onChange={onChange}
        />
      </Theme>,
    );

    expect(screen.getByText("Set by team admin")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Always Allow" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Needs Approval" })).toBeEnabled();
    expect(screen.getByRole("radio", { name: "Blocked" })).toBeEnabled();

    await user.click(screen.getByRole("radio", { name: "Blocked" }));
    expect(onChange).toHaveBeenCalledWith("do_not_use");
  });

  it("uses the exact approval names", () => {
    render(
      <Theme>
        <GatewayToolRow policy={policy} editable onChange={vi.fn()} />
      </Theme>,
    );

    expect(
      screen.getByRole("radio", { name: "Always Allow" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Needs Approval" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Blocked" })).toBeInTheDocument();
  });

  it("removes approval from agent settings and treats legacy approval as blocked", () => {
    render(
      <Theme>
        <GatewayToolRow
          policy={policy}
          editable
          agentScope
          onChange={vi.fn()}
        />
      </Theme>,
    );

    expect(
      screen.getByRole("radio", { name: "Always Allow" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("radio", { name: "Needs Approval" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Blocked" })).toBeChecked();
  });

  it("lets an admin raise the team ceiling while editing the team scope", () => {
    render(
      <Theme>
        <GatewayToolRow
          policy={{
            ...policy,
            team_state: "needs_approval",
            decided_by: "team",
          }}
          editable
          teamScope
          onChange={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.queryByText("Set by team admin")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Always Allow" })).toBeEnabled();
  });
});
