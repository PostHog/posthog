import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { consumeDeferredCredentials } from "./deferred-credentials";

describe("consumeDeferredCredentials", () => {
  it("loads and removes the one-shot credential file", async () => {
    const directory = await mkdtemp(join(tmpdir(), "agent-credentials-"));
    const path = join(directory, "credentials.json");
    await writeFile(
      path,
      JSON.stringify({
        mcpServers: [
          {
            type: "http",
            name: "posthog",
            url: "https://mcp.example.test/mcp",
            headers: [{ name: "Authorization", value: "Bearer secret" }],
          },
        ],
        eventIngestToken: "event-token",
        taskRunSessionToken: "session-token",
      }),
    );

    await expect(consumeDeferredCredentials(path)).resolves.toMatchObject({
      eventIngestToken: "event-token",
      taskRunSessionToken: "session-token",
    });
    await expect(readFile(path)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("removes an invalid credential file", async () => {
    const directory = await mkdtemp(join(tmpdir(), "agent-credentials-"));
    const path = join(directory, "credentials.json");
    await writeFile(path, '{"eventIngestToken":""}');

    await expect(consumeDeferredCredentials(path)).rejects.toBeDefined();
    await expect(readFile(path)).rejects.toMatchObject({ code: "ENOENT" });
  });
});
