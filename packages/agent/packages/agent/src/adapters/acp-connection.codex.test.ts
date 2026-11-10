import { describe, expect, it, vi } from "vitest";

const codexAgentOptions = vi.hoisted(() => [] as unknown[]);

vi.mock("./codex-app-server/binary-path", () => ({
  nativeCodexBinaryPath: () => "/bin/codex",
}));
vi.mock("./codex-app-server/codex-app-server-agent", () => ({
  CodexAppServerAgent: vi.fn(function (this: unknown, _client, options) {
    codexAgentOptions.push(options);
    return {};
  }),
}));

import { createAcpConnection } from "./acp-connection";

describe("createAcpConnection codex options", () => {
  it("forwards the config-file base URL flag to the codex process", async () => {
    const connection = createAcpConnection({
      adapter: "codex",
      taskRunId: "run-1",
      taskId: "task-1",
      codexOptions: {
        apiBaseUrl: "http://127.0.0.1:5000/token/v1",
        apiBaseUrlInConfig: true,
        codexHome: "/tmp/codex-home",
      },
    });

    await vi.waitFor(() => expect(codexAgentOptions).toHaveLength(1));
    expect(codexAgentOptions[0]).toMatchObject({
      processOptions: {
        apiBaseUrl: "http://127.0.0.1:5000/token/v1",
        apiBaseUrlInConfig: true,
        codexHome: "/tmp/codex-home",
      },
    });
    await connection.cleanup().catch(() => undefined);
  });
});
