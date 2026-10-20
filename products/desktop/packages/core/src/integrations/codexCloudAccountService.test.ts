import type { UserCodexIntegration } from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import {
  CodexCloudAccountService,
  type CodexCloudTerminal,
} from "./codexCloudAccountService";

const tokens = {
  access_token: "access-example",
  refresh_token: "refresh-example",
  id_token: null,
};

const connected: UserCodexIntegration = {
  status: "connected",
  plan_type: "plus",
  email: "user@example.com",
  connected_at: "2026-01-01T00:00:00Z",
};

describe("connectCodexCloudAccount", () => {
  it("waits for preparation before it cancels the login", async () => {
    let prepared!: (terminal: CodexCloudTerminal) => void;
    const preparation = new Promise<CodexCloudTerminal>((resolve) => {
      prepared = resolve;
    });
    const host = {
      prepare: vi.fn().mockReturnValue(preparation),
      finish: vi.fn(),
      cancel: vi.fn().mockResolvedValue(undefined),
      read: vi.fn(),
      remove: vi.fn(),
    };
    const service = new CodexCloudAccountService(host);
    const login = service.begin("attempt-1");
    const cancel = service.cancel("attempt-1");
    expect(host.cancel).not.toHaveBeenCalled();
    prepared({
      command: "codex",
      cwd: "/tmp",
      additionalEnv: {},
      unsetEnv: [],
    });
    await login;
    await cancel;
    expect(host.cancel).toHaveBeenCalledWith("attempt-1");
    await service.begin("attempt-2");
  });

  it("removes the local login file only after PostHog accepted the tokens", async () => {
    let finishUpload!: (value: UserCodexIntegration) => void;
    const upload = new Promise<UserCodexIntegration>((resolve) => {
      finishUpload = resolve;
    });
    const client = {
      connectCodexUserIntegration: vi.fn().mockReturnValue(upload),
    };
    const host = {
      prepare: vi.fn().mockResolvedValue({
        command: "codex",
        cwd: "/tmp",
        additionalEnv: {},
        unsetEnv: [],
      }),
      finish: vi.fn().mockResolvedValue(undefined),
      cancel: vi.fn().mockResolvedValue(undefined),
      read: vi.fn().mockResolvedValue(tokens),
      remove: vi.fn().mockResolvedValue(undefined),
    };

    const service = new CodexCloudAccountService(host);
    await service.begin("attempt-1");
    const connection = service.connect("attempt-1", client);
    const cancelled = service.cancel("attempt-1");
    await expect(service.begin("attempt-2")).rejects.toThrow("in progress");
    expect(service.connect("attempt-1", client)).toBe(connection);
    expect(host.remove).not.toHaveBeenCalled();
    finishUpload(connected);
    await expect(connection).resolves.toEqual({
      integration: connected,
      staleFileError: null,
    });

    expect(client.connectCodexUserIntegration).toHaveBeenCalledWith(tokens);
    await cancelled;
    expect(host.remove).toHaveBeenCalledWith("attempt-1");
    await service.begin("attempt-2");
    await service.cancel("attempt-1");
    expect(host.cancel).not.toHaveBeenCalled();
    await service.cancel("attempt-2");
  });

  it("reports a connect that left the stale file behind as connected", async () => {
    const client = {
      connectCodexUserIntegration: vi.fn().mockResolvedValue(connected),
    };
    const host = {
      prepare: vi.fn().mockResolvedValue({
        command: "codex",
        cwd: "/tmp",
        additionalEnv: {},
        unsetEnv: [],
      }),
      finish: vi.fn().mockResolvedValue(undefined),
      cancel: vi.fn().mockResolvedValue(undefined),
      read: vi.fn().mockResolvedValue(tokens),
      remove: vi.fn().mockRejectedValue(new Error("EACCES")),
    };

    const service = new CodexCloudAccountService(host);
    await service.begin("attempt-1");
    await expect(service.connect("attempt-1", client)).resolves.toEqual({
      integration: connected,
      staleFileError: new Error("EACCES"),
    });
  });

  it("keeps the local login file when PostHog rejects the tokens", async () => {
    const client = {
      connectCodexUserIntegration: vi
        .fn()
        .mockRejectedValue(new Error("OpenAI rejected the login")),
    };
    const host = {
      prepare: vi.fn().mockResolvedValue({
        command: "codex",
        cwd: "/tmp",
        additionalEnv: {},
        unsetEnv: [],
      }),
      finish: vi.fn().mockResolvedValue(undefined),
      cancel: vi.fn().mockResolvedValue(undefined),
      read: vi.fn().mockResolvedValue(tokens),
      remove: vi.fn().mockResolvedValue(undefined),
    };

    const service = new CodexCloudAccountService(host);
    await service.begin("attempt-1");
    await expect(service.connect("attempt-1", client)).rejects.toThrow(
      "OpenAI rejected the login",
    );

    expect(host.remove).not.toHaveBeenCalled();
  });
});
