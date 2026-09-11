import type {
  Client,
  RequestPermissionRequest,
} from "@agentclientprotocol/sdk";
import { describe, expect, it, vi } from "vitest";
import { openConnection } from "./driver";

const host = vi.hoisted(() => ({ client: undefined as Client | undefined }));

vi.mock("@agentclientprotocol/sdk", () => ({
  ClientSideConnection: class {
    constructor(createClient: () => Client) {
      host.client = createClient();
    }
  },
  ndJsonStream: vi.fn(),
}));

vi.mock("../src/adapters/acp-connection", () => ({
  createAcpConnection: () => ({ clientStreams: {} }),
}));

describe("live e2e host permissions", () => {
  it.each([
    {
      kind: "switch_mode",
      optionId: "auto",
      outcome: { outcome: "cancelled" },
    },
    {
      kind: "other",
      optionId: "option_0",
      outcome: { outcome: "selected", optionId: "option_0" },
    },
    {
      kind: "edit",
      optionId: "allow",
      outcome: { outcome: "selected", optionId: "allow" },
    },
  ] as const)(
    "responds to $kind without starting unrequested implementation turns",
    async ({ kind, optionId, outcome }) => {
      const { capture } = openConnection({ adapter: "claude", cwd: "/tmp" });
      const request = {
        sessionId: "session",
        toolCall: { toolCallId: "tool", title: "Test permission", kind },
        options: [{ kind: "allow_once", optionId, name: "Allow" }],
      } as unknown as RequestPermissionRequest;

      expect(await host.client?.requestPermission(request)).toEqual({
        outcome,
      });
      expect(capture.approvals()).toHaveLength(1);
    },
  );
});
