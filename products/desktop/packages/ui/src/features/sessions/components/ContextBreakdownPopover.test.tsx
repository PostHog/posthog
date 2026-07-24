import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContextBreakdownPopover } from "./ContextBreakdownPopover";

function usageWith(
  breakdown: ContextUsage["breakdown"],
  overrides?: Partial<ContextUsage>,
): ContextUsage {
  return {
    used: 74_000,
    size: 200_000,
    percentage: 37,
    cost: null,
    breakdown,
    ...overrides,
  };
}

describe("ContextBreakdownPopover", () => {
  it("renders the header with aggregate tokens", () => {
    render(
      <Theme>
        <ContextBreakdownPopover usage={usageWith(null)} />
      </Theme>,
    );
    expect(screen.getByText(/74K \/ 200K tokens/)).toBeInTheDocument();
    expect(screen.getByText("37% full")).toBeInTheDocument();
  });

  it("shows only the token count when the context window is unknown (size 0)", () => {
    render(
      <Theme>
        <ContextBreakdownPopover
          usage={usageWith(null, { used: 50_000, size: 0, percentage: 0 })}
        />
      </Theme>,
    );
    // No misleading "/ 0 tokens" denominator or "0% full" line.
    expect(screen.getByText("~50K tokens")).toBeInTheDocument();
    expect(screen.queryByText(/\/ 0 tokens/)).not.toBeInTheDocument();
    expect(screen.queryByText(/% full/)).not.toBeInTheDocument();
  });

  it("shows the placeholder copy when breakdown is missing", () => {
    render(
      <Theme>
        <ContextBreakdownPopover usage={usageWith(null)} />
      </Theme>,
    );
    expect(
      screen.getByText(/Detailed breakdown available after the first response/),
    ).toBeInTheDocument();
  });

  it("renders one row per non-zero category", () => {
    render(
      <Theme>
        <ContextBreakdownPopover
          usage={usageWith({
            systemPrompt: 4000,
            tools: 0,
            rules: 0,
            skills: 0,
            mcp: 1500,
            subagents: 0,
            conversation: 68_500,
          })}
        />
      </Theme>,
    );
    expect(screen.getByText("System prompt")).toBeInTheDocument();
    expect(screen.getByText("MCP")).toBeInTheDocument();
    expect(screen.getByText("Conversation")).toBeInTheDocument();
    expect(screen.queryByText("Tools")).not.toBeInTheDocument();
    expect(screen.queryByText("Rules")).not.toBeInTheDocument();
  });

  it("scales segments to the context window, not the used tokens", () => {
    const { container } = render(
      <Theme>
        <ContextBreakdownPopover
          usage={usageWith(
            {
              systemPrompt: 0,
              tools: 0,
              rules: 0,
              skills: 0,
              mcp: 0,
              subagents: 0,
              conversation: 50_000,
            },
            { used: 50_000, size: 200_000, percentage: 25 },
          )}
        />
      </Theme>,
    );
    // 50K of a 200K window => the single segment fills a quarter of the bar,
    // leaving the rest as empty track (remaining context).
    const segment = container.querySelector('[style*="width: 25%"]');
    expect(segment).not.toBeNull();
  });
});
