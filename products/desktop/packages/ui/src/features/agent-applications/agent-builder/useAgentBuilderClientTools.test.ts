import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}));

const client = {
  getAgentApplication: vi.fn(),
  listAgentRevisions: vi.fn(),
  getAgentRevision: vi.fn(),
};

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => client,
}));

import type { ClientToolCallData } from "@posthog/core/agent-chat/identifiers";
import { useAgentBuilderStore } from "./agentBuilderStore";
import { useAgentBuilderClientTools } from "./useAgentBuilderClientTools";

function call(
  tool_id: string,
  args: Record<string, unknown>,
): ClientToolCallData {
  return { call_id: "call-1", tool_id, args };
}

function handler() {
  return renderHook(() => useAgentBuilderClientTools()).result.current;
}

describe("useAgentBuilderClientTools revision resolution", () => {
  beforeEach(() => {
    client.getAgentApplication.mockReset();
    client.listAgentRevisions.mockReset();
    client.getAgentRevision.mockReset();
    useAgentBuilderStore.setState({
      page: { kind: "unknown" },
      pendingSecret: null,
      pendingMcpConnect: null,
    });
  });

  it("uses an explicit revision_id once it verifies as belonging to the agent", async () => {
    client.getAgentRevision.mockResolvedValue({ id: "rev-explicit" });

    const outcome = await handler()(
      call("set_secret", {
        agent_slug: "my-agent",
        secret: "API_KEY",
        revision_id: "rev-explicit",
      }),
    );

    expect(outcome).toEqual({ defer: true });
    expect(useAgentBuilderStore.getState().pendingSecret).toMatchObject({
      agentSlug: "my-agent",
      secret: "API_KEY",
      revisionId: "rev-explicit",
    });
    expect(client.getAgentRevision).toHaveBeenCalledWith(
      "my-agent",
      "rev-explicit",
    );
    expect(client.getAgentApplication).not.toHaveBeenCalled();
    expect(client.listAgentRevisions).not.toHaveBeenCalled();
  });

  it("rejects an explicit revision_id that does not belong to the agent", async () => {
    // The nested revision route 404s (→ null) for another agent's revision.
    client.getAgentRevision.mockResolvedValue(null);

    const outcome = await handler()(
      call("set_secret", {
        agent_slug: "my-agent",
        secret: "API_KEY",
        revision_id: "rev-of-other-agent",
      }),
    );

    expect(outcome).toEqual({
      error: "revision_not_found: rev-of-other-agent on my-agent",
    });
    expect(useAgentBuilderStore.getState().pendingSecret).toBeNull();
  });

  it("falls back to the revision open on this agent's config page", async () => {
    useAgentBuilderStore.setState({
      page: { kind: "agent-config", slug: "my-agent", revision: "rev-page" },
    });

    const outcome = await handler()(
      call("set_secret", { agent_slug: "my-agent", secret: "API_KEY" }),
    );

    expect(outcome).toEqual({ defer: true });
    expect(useAgentBuilderStore.getState().pendingSecret?.revisionId).toBe(
      "rev-page",
    );
    expect(client.getAgentApplication).not.toHaveBeenCalled();
  });

  it("rotation targets live even while a draft config page is open", async () => {
    useAgentBuilderStore.setState({
      page: { kind: "agent-config", slug: "my-agent", revision: "rev-draft" },
    });
    client.getAgentApplication.mockResolvedValue({ live_revision: "rev-live" });
    client.listAgentRevisions.mockResolvedValue([
      { id: "rev-draft", state: "draft" },
      { id: "rev-live", state: "ready" },
    ]);

    await handler()(
      call("set_secret", {
        agent_slug: "my-agent",
        secret: "API_KEY",
        mode: "rotate",
      }),
    );

    expect(useAgentBuilderStore.getState().pendingSecret?.revisionId).toBe(
      "rev-live",
    );
  });

  it("ignores the page revision when it belongs to a different agent", async () => {
    useAgentBuilderStore.setState({
      page: { kind: "agent-config", slug: "other-agent", revision: "rev-page" },
    });
    client.getAgentApplication.mockResolvedValue({ live_revision: null });
    client.listAgentRevisions.mockResolvedValue([
      { id: "rev-draft", state: "draft" },
    ]);

    await handler()(
      call("set_secret", { agent_slug: "my-agent", secret: "API_KEY" }),
    );

    expect(useAgentBuilderStore.getState().pendingSecret?.revisionId).toBe(
      "rev-draft",
    );
  });

  it.each([
    // A new secret targets the draft being authored (secrets only copy
    // forward at draft creation), even when a live revision exists.
    { mode: "set", expected: "rev-draft" },
    // A rotation targets what's running.
    { mode: "rotate", expected: "rev-live" },
  ])(
    "set_secret mode=$mode resolves to $expected via the API",
    async ({ mode, expected }) => {
      client.getAgentApplication.mockResolvedValue({
        live_revision: "rev-live",
      });
      client.listAgentRevisions.mockResolvedValue([
        { id: "rev-draft", state: "draft" },
        { id: "rev-live", state: "ready" },
      ]);

      await handler()(
        call("set_secret", { agent_slug: "my-agent", secret: "API_KEY", mode }),
      );

      expect(useAgentBuilderStore.getState().pendingSecret?.revisionId).toBe(
        expected,
      );
    },
  );

  it("set_secret falls back to the newest revision when no live or draft exists", async () => {
    client.getAgentApplication.mockResolvedValue({ live_revision: null });
    client.listAgentRevisions.mockResolvedValue([
      { id: "rev-newest", state: "ready" },
      { id: "rev-older", state: "ready" },
    ]);

    await handler()(
      call("set_secret", { agent_slug: "my-agent", secret: "API_KEY" }),
    );

    expect(useAgentBuilderStore.getState().pendingSecret?.revisionId).toBe(
      "rev-newest",
    );
  });

  it("errors when the agent has no revisions at all", async () => {
    client.getAgentApplication.mockResolvedValue({ live_revision: null });
    client.listAgentRevisions.mockResolvedValue([]);

    const outcome = await handler()(
      call("set_secret", { agent_slug: "my-agent", secret: "API_KEY" }),
    );

    expect(outcome).toEqual({ error: "no_target_revision: my-agent" });
    expect(useAgentBuilderStore.getState().pendingSecret).toBeNull();
  });

  it("errors when revision lookup fails", async () => {
    client.getAgentApplication.mockRejectedValue(new Error("network"));
    client.listAgentRevisions.mockRejectedValue(new Error("network"));

    const outcome = await handler()(
      call("set_secret", { agent_slug: "my-agent", secret: "API_KEY" }),
    );

    expect(outcome).toEqual({ error: "no_target_revision: my-agent" });
  });

  it("connect_mcp prefers the newest draft (spec edits are draft-only)", async () => {
    client.getAgentApplication.mockResolvedValue({
      live_revision: "rev-live",
    });
    client.listAgentRevisions.mockResolvedValue([
      { id: "rev-draft", state: "draft" },
      { id: "rev-live", state: "ready" },
    ]);

    const outcome = await handler()(
      call("connect_mcp", { agent_slug: "my-agent", url: "https://mcp.test" }),
    );

    expect(outcome).toEqual({ defer: true });
    expect(useAgentBuilderStore.getState().pendingMcpConnect).toMatchObject({
      agentSlug: "my-agent",
      revisionId: "rev-draft",
      url: "https://mcp.test",
    });
  });
});
