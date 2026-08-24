import type { McpInstallationTool } from "@posthog/api-client/types";
import { describe, expect, it, vi } from "vitest";
import { dispatchBulkApproval } from "./toolBulk";

function tool(
  name: string,
  overrides: Partial<McpInstallationTool> = {},
): McpInstallationTool {
  return {
    id: `tool-${name}`,
    tool_name: name,
    display_name: name,
    description: "",
    input_schema: {},
    approval_state: "needs_approval",
    last_seen_at: "2026-01-01T00:00:00Z",
    removed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("dispatchBulkApproval", () => {
  it("calls updateMcpToolApproval once per non-removed tool with the chosen state", async () => {
    const update = vi.fn().mockResolvedValue(undefined);
    const tools = [
      tool("a"),
      tool("b"),
      tool("c", { removed_at: "2026-04-01T00:00:00Z" }),
    ];

    await dispatchBulkApproval(
      { updateMcpToolApproval: update },
      "inst-1",
      tools,
      "approved",
    );

    expect(update).toHaveBeenCalledTimes(2);
    expect(update).toHaveBeenCalledWith("inst-1", "a", "approved");
    expect(update).toHaveBeenCalledWith("inst-1", "b", "approved");
    expect(update).not.toHaveBeenCalledWith(
      expect.anything(),
      "c",
      expect.anything(),
    );
  });

  it("fires requests in parallel rather than sequentially", async () => {
    let concurrent = 0;
    let peak = 0;
    const update = vi.fn(async () => {
      concurrent += 1;
      peak = Math.max(peak, concurrent);
      await new Promise((r) => setTimeout(r, 5));
      concurrent -= 1;
    });

    await dispatchBulkApproval(
      { updateMcpToolApproval: update },
      "inst-1",
      [tool("a"), tool("b"), tool("c")],
      "do_not_use",
    );

    expect(peak).toBeGreaterThan(1);
  });

  it("rejects if any update fails", async () => {
    const update = vi.fn(async (_id: string, name: string) => {
      if (name === "b") throw new Error("boom");
    });

    await expect(
      dispatchBulkApproval(
        { updateMcpToolApproval: update },
        "inst-1",
        [tool("a"), tool("b"), tool("c")],
        "approved",
      ),
    ).rejects.toThrow("boom");
  });

  it("is a no-op when the tool list is empty", async () => {
    const update = vi.fn().mockResolvedValue(undefined);
    await dispatchBulkApproval(
      { updateMcpToolApproval: update },
      "inst-1",
      [],
      "approved",
    );
    expect(update).not.toHaveBeenCalled();
  });
});
