import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Page } from "@playwright/test";
import type { HostRouter } from "@posthog/host-router/router";
import type { inferRouterInputs, inferRouterOutputs } from "@trpc/server";
import { expect, test } from "../fixtures/electron";

const PLUGIN_SCHEMA =
  "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json";
const MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json";
const MCP_SERVER_SOURCE = `
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

const pluginData = process.env.PLUGIN_DATA;
if (!pluginData) process.exit(1);

const input = readline.createInterface({ input: process.stdin });
input.on("line", (line) => {
  const message = JSON.parse(line);
  if (message.id === undefined) return;

  const result =
    message.method === "initialize"
      ? {
          protocolVersion: "2025-06-18",
          capabilities: { tools: {} },
          serverInfo: { name: "agent-plugin-e2e", version: "1.0.0" },
        }
      : message.method === "tools/list"
        ? {
            tools: [
              {
                name: "echo",
                description: "Echo text",
                inputSchema: { type: "object" },
              },
            ],
          }
        : {};

  if (message.method === "initialize") {
    fs.writeFileSync(path.join(pluginData, "initialize-requested"), "ready");
  }
  process.stdout.write(
    JSON.stringify({ jsonrpc: "2.0", id: message.id, result }) + "\\n",
  );
});
`;

type HostRouterInputs = inferRouterInputs<HostRouter>;
type HostRouterOutputs = inferRouterOutputs<HostRouter>;
type AgentPluginInputs = HostRouterInputs["agentPlugins"];
type AgentPluginOutputs = HostRouterOutputs["agentPlugins"];
type AgentPluginProcedure = keyof AgentPluginInputs & keyof AgentPluginOutputs;
type AgentPluginRouterRecord = HostRouter["_def"]["record"]["agentPlugins"];
type AgentPluginOperation<TProcedure extends AgentPluginProcedure> =
  AgentPluginRouterRecord[TProcedure]["_def"]["type"];
type AgentPluginInputArguments<TProcedure extends AgentPluginProcedure> =
  undefined extends AgentPluginInputs[TProcedure]
    ? [input?: AgentPluginInputs[TProcedure]]
    : [input: AgentPluginInputs[TProcedure]];
type AgentProcedure = "start" | "cancel";
type AgentRouterRecord = HostRouter["_def"]["record"]["agent"];
type AgentOperation<TProcedure extends AgentProcedure> =
  AgentRouterRecord[TProcedure]["_def"]["type"];
type AgentInputArguments<TProcedure extends AgentProcedure> =
  undefined extends HostRouterInputs["agent"][TProcedure]
    ? [input?: HostRouterInputs["agent"][TProcedure]]
    : [input: HostRouterInputs["agent"][TProcedure]];

async function callHostProcedure(
  window: Page,
  path: string,
  type: "query" | "mutation",
  input: unknown,
): Promise<unknown> {
  return window.evaluate(
    ({ input, path, type }) =>
      new Promise<unknown>((resolve, reject) => {
        interface HostTrpcResponse {
          id: string;
          result?: { type: string; data?: unknown };
          error?: unknown;
        }

        interface HostTrpcBridge {
          sendMessage: (message: {
            method: "request";
            operation: {
              id: string;
              type: "query" | "mutation";
              path: string;
              input?: unknown;
              context: Record<string, never>;
            };
          }) => void;
          onMessage: (callback: (response: HostTrpcResponse) => void) => void;
        }

        const bridge = (
          globalThis as unknown as { electronTRPC: HostTrpcBridge }
        ).electronTRPC;
        const id = `agent-plugins-e2e-${crypto.randomUUID()}`;

        bridge.onMessage((response) => {
          if (response.id !== id) return;
          if (response.error) {
            reject(new Error(JSON.stringify(response.error)));
            return;
          }
          if (response.result?.type !== "data") return;

          const data = response.result.data;
          if (data && typeof data === "object" && "json" in data) {
            resolve((data as { json: unknown }).json);
            return;
          }
          resolve(data);
        });

        bridge.sendMessage({
          method: "request",
          operation: {
            id,
            type,
            path,
            input: input === undefined ? undefined : { json: input },
            context: {},
          },
        });
      }),
    { input, path, type },
  );
}

async function callAgentPluginProcedure<
  TProcedure extends AgentPluginProcedure,
>(
  window: Page,
  procedure: TProcedure,
  type: AgentPluginOperation<TProcedure>,
  ...inputArguments: AgentPluginInputArguments<TProcedure>
): Promise<AgentPluginOutputs[TProcedure]> {
  return callHostProcedure(
    window,
    `agentPlugins.${procedure}`,
    type,
    inputArguments[0],
  ) as Promise<AgentPluginOutputs[TProcedure]>;
}

async function callAgentProcedure<TProcedure extends AgentProcedure>(
  window: Page,
  procedure: TProcedure,
  type: AgentOperation<TProcedure>,
  ...inputArguments: AgentInputArguments<TProcedure>
): Promise<HostRouterOutputs["agent"][TProcedure]> {
  return callHostProcedure(
    window,
    `agent.${procedure}`,
    type,
    inputArguments[0],
  ) as Promise<HostRouterOutputs["agent"][TProcedure]>;
}

test.use({
  electronEnv: {
    POSTHOG_MCP_URL: "http://127.0.0.1:1/mcp",
  },
});

test.describe("Agent Plugins", () => {
  test("prepares a plugin skill and MCP server for an agent session", async ({
    electronApp,
    window,
  }) => {
    const { e2eHome, userDataPath } = await electronApp.evaluate(({ app }) => ({
      e2eHome: app.getPath("home"),
      userDataPath: app.getPath("userData"),
    }));
    const pluginDirectory = path.join(e2eHome, "agent-plugin-e2e");
    const skillDirectory = path.join(
      pluginDirectory,
      "skills",
      "release-notes",
    );
    await mkdir(skillDirectory, { recursive: true });
    await writeFile(
      path.join(pluginDirectory, "plugin.json"),
      `${JSON.stringify({
        $schema: PLUGIN_SCHEMA,
        name: "agent-plugin-e2e",
        version: "1.0.0",
        description: "Exercises the Agent Plugins Electron integration.",
      })}\n`,
    );
    await writeFile(
      path.join(skillDirectory, "SKILL.md"),
      `---\nname: release-notes\ndescription: Draft release notes from completed work.\n---\n\nSummarize completed work.\n`,
    );
    await writeFile(
      path.join(pluginDirectory, "server.mjs"),
      MCP_SERVER_SOURCE,
    );
    await writeFile(
      path.join(pluginDirectory, "mcp.json"),
      `${JSON.stringify({
        $schema: MCP_SCHEMA,
        mcpServers: {
          "local-tools": {
            type: "stdio",
            command: "node",
            args: ["$" + "{PLUGIN_ROOT}/server.mjs"],
          },
        },
      })}\n`,
    );

    await electronApp.evaluate(({ dialog }, selectedDirectory) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [selectedDirectory],
      });
    }, pluginDirectory);

    const preview = await callAgentPluginProcedure(
      window,
      "select",
      "mutation",
    );
    if (!preview) {
      throw new Error("Agent Plugin directory selection was canceled");
    }
    expect(preview.valid).toBe(true);
    expect(preview.manifest?.name).toBe("agent-plugin-e2e");
    expect(preview.skills.map((skill) => skill.name)).toEqual([
      "release-notes",
    ]);
    expect(preview.mcpServers).toEqual([
      expect.objectContaining({
        name: "local-tools",
        type: "stdio",
        approval: "required",
      }),
    ]);
    expect(preview.selectionToken).toBeTruthy();
    if (!preview.selectionToken) {
      throw new Error("Agent Plugin preview did not include a selection token");
    }

    const registered = await callAgentPluginProcedure(
      window,
      "register",
      "mutation",
      { selectionToken: preview.selectionToken },
    );
    expect(registered.enabled).toBe(true);
    expect(registered.skills).toHaveLength(1);
    expect(registered.mcpServers).toEqual([
      expect.objectContaining({
        name: "local-tools",
        type: "stdio",
        approval: "approved",
      }),
    ]);

    const taskRunId = "agent-plugin-e2e-run";
    const session = await callAgentProcedure(window, "start", "mutation", {
      taskId: "__preview__",
      taskRunId,
      repoPath: e2eHome,
      apiHost: "http://127.0.0.1:1",
      projectId: 1,
      adapter: "codex",
      permissionMode: "bypassPermissions",
      rtkEnabled: false,
    });
    try {
      const loadedSkillPath = path.join(
        userDataPath,
        "codex-home",
        taskRunId,
        "skills",
        "release-notes",
        "SKILL.md",
      );
      await expect
        .poll(() => readFile(loadedSkillPath, "utf8").catch(() => "not loaded"))
        .toContain("name: release-notes");

      const mcpMarkerPath = path.join(
        userDataPath,
        "agent-plugins",
        "data",
        registered.id,
        "initialize-requested",
      );
      await expect
        .poll(() => readFile(mcpMarkerPath, "utf8").catch(() => "not ready"))
        .toBe("ready");
    } finally {
      await callAgentProcedure(window, "cancel", "mutation", {
        sessionId: session.sessionId,
      });
    }

    const disabled = await callAgentPluginProcedure(
      window,
      "setEnabled",
      "mutation",
      { id: registered.id, enabled: false },
    );
    expect(disabled.enabled).toBe(false);

    const installations = await callAgentPluginProcedure(
      window,
      "list",
      "query",
    );
    expect(installations).toEqual([
      expect.objectContaining({
        id: registered.id,
        enabled: false,
        manifest: expect.objectContaining({ name: "agent-plugin-e2e" }),
      }),
    ]);

    await callAgentPluginProcedure(window, "unregister", "mutation", {
      id: registered.id,
    });
    await expect
      .poll(() => callAgentPluginProcedure(window, "list", "query"))
      .toEqual([]);
  });
});
