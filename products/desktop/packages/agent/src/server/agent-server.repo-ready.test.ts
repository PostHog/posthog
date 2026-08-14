import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { AgentServer } from "./agent-server";

describe("AgentServer repository barrier", () => {
  let repositoryPath: string | undefined;

  afterEach(async () => {
    if (repositoryPath) await rm(repositoryPath, { recursive: true });
  });

  it("rejects deferred credentials without a repository barrier", async () => {
    repositoryPath = await mkdtemp(join(tmpdir(), "agent-server-barrier-"));
    const server = new AgentServer({
      port: 0,
      repositoryPath,
      apiUrl: "https://app.example.com",
      apiKey: "test-api-key",
      projectId: 1,
      jwtPublicKey: "test-public-key",
      mode: "interactive",
      taskId: "test-task-id",
      runId: "test-run-id",
      deferredCredentialsFile: join(repositoryPath, "agent-credentials"),
      resolveRtkSavings: async () => null,
    }) as unknown as { waitForRepoReady(): Promise<void> };

    await expect(server.waitForRepoReady()).rejects.toThrow(
      "Deferred credentials require a repository-ready barrier",
    );
  });
});
