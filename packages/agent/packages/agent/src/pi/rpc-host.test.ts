import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import type { TaskContext } from "@posthog/agent-contracts/task-context";
import { build } from "tsup";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { createPiRpcClient, createRuntimeMcpStdioServers } from "./rpc-client";

let hostDirectory: string;

beforeAll(async () => {
  hostDirectory = await mkdtemp(
    fileURLToPath(new URL(".rpc-host-test-", import.meta.url)),
  );
  await build({
    entry: { host: fileURLToPath(new URL("./rpc-host.ts", import.meta.url)) },
    outDir: hostDirectory,
    format: ["esm"],
    target: "node22",
    config: false,
    silent: true,
  });
}, 30_000);

afterAll(async () => {
  if (hostDirectory) {
    await rm(hostDirectory, { recursive: true, force: true });
  }
});

describe("Pi RPC host project trust", () => {
  it.each([
    { environment: "cloud" as const, trusted: false },
    { environment: "local" as const, trusted: true },
    { environment: undefined, trusted: false },
  ])(
    "applies $environment project trust on startup and resume",
    async ({ environment, trusted }) => {
      const directory = await mkdtemp(join(tmpdir(), "pi-project-trust-"));
      const cwd = join(directory, "repository");
      const projectDirectory = join(cwd, ".pi");
      const extensionMarker = join(directory, "extension-loaded");
      const credentialMarker = join(directory, "credential-readable");
      const mcpMarker = join(directory, "mcp-started");
      const runtimeMcpMarker = join(directory, "runtime-mcp-started");
      const home = join(directory, "home");
      await mkdir(join(projectDirectory, "extensions"), { recursive: true });
      await mkdir(home);
      await writeFile(
        join(projectDirectory, "extensions", "project.ts"),
        `
import { writeFileSync } from "node:fs";
writeFileSync(${JSON.stringify(extensionMarker)}, "loaded");
export default function (pi) {
  pi.on("session_start", async (_event, ctx) => {
    const key = await ctx.modelRegistry.getApiKeyForProvider("posthog");
    writeFileSync(${JSON.stringify(credentialMarker)}, String(key === "test-provider-key"));
  });
}
`,
      );
      await writeFile(
        join(projectDirectory, "mcp.json"),
        JSON.stringify({
          mcpServers: {
            project: {
              command: process.execPath,
              args: [
                "-e",
                `require("node:fs").writeFileSync(${JSON.stringify(mcpMarker)}, "started")`,
              ],
              lifecycle: "eager",
            },
          },
        }),
      );

      vi.stubEnv("HOME", home);
      try {
        const persistedMessage = {
          role: "user" as const,
          content: [
            { type: "text" as const, text: "Remember this conversation." },
          ],
          timestamp: Date.now(),
        };
        const session = SessionManager.create(cwd, join(directory, "sessions"));
        session.appendMessage(persistedMessage);
        const sessionFile = session.getSessionFile();
        for (const resume of [false, true]) {
          if (resume) {
            expect(sessionFile && existsSync(sessionFile)).toBe(true);
          }
          const client = createPiRpcClient({
            cliPath: join(hostDirectory, "host.js"),
            sessionFile: resume ? sessionFile : undefined,
            taskContext: {
              taskId: "test-task",
              cwd,
              projectId: 1,
              apiHost: "https://example.com",
              environment,
            } as TaskContext,
            providerOptions: { apiKey: "test-provider-key" },
            runtimeMcpServers: createRuntimeMcpStdioServers([
              {
                name: "runtime",
                command: process.execPath,
                args: [
                  "-e",
                  `require("node:fs").writeFileSync(${JSON.stringify(runtimeMcpMarker)}, "started")`,
                ],
              },
            ]),
          });
          try {
            await client.start();
            const state = await client.getState();
            expect(state.sessionFile).toBeTruthy();
            if (resume) {
              expect(state).toMatchObject({
                sessionFile,
                sessionId: session.getSessionId(),
              });
            }
            expect(await client.getMessages()).toEqual(
              resume ? [persistedMessage] : [],
            );
            expect(state.model?.provider).toBe("posthog");
            expect(await client.getCommands()).toEqual(
              expect.arrayContaining([
                expect.objectContaining({ name: "mcp" }),
              ]),
            );
            expect({
              extensionLoaded: existsSync(extensionMarker),
              credentialReadable: existsSync(credentialMarker)
                ? await readFile(credentialMarker, "utf8")
                : null,
              projectMcpStarted: existsSync(mcpMarker),
              runtimeMcpStarted: existsSync(runtimeMcpMarker),
            }).toEqual({
              extensionLoaded: trusted,
              credentialReadable: trusted ? "true" : null,
              projectMcpStarted: trusted,
              runtimeMcpStarted: true,
            });
          } finally {
            await client.stop();
          }
          await Promise.all(
            [
              extensionMarker,
              credentialMarker,
              mcpMarker,
              runtimeMcpMarker,
            ].map((path) => rm(path, { force: true })),
          );
        }
      } finally {
        vi.unstubAllEnvs();
        await rm(directory, { recursive: true, force: true });
      }
    },
    30_000,
  );
});
