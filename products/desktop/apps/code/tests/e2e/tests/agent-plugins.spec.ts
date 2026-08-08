import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Page } from "@playwright/test";
import type { HostRouter } from "@posthog/host-router/router";
import type { inferRouterInputs, inferRouterOutputs } from "@trpc/server";
import { expect, test } from "../fixtures/electron";

const PLUGIN_SCHEMA =
  "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json";
const MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json";

type AgentPluginInputs = inferRouterInputs<HostRouter>["agentPlugins"];
type AgentPluginOutputs = inferRouterOutputs<HostRouter>["agentPlugins"];
type AgentPluginProcedure = keyof AgentPluginInputs & keyof AgentPluginOutputs;
type AgentPluginRouterRecord = HostRouter["_def"]["record"]["agentPlugins"];
type AgentPluginOperation<TProcedure extends AgentPluginProcedure> =
  AgentPluginRouterRecord[TProcedure]["_def"]["type"];
type AgentPluginInputArguments<TProcedure extends AgentPluginProcedure> =
  undefined extends AgentPluginInputs[TProcedure]
    ? [input?: AgentPluginInputs[TProcedure]]
    : [input: AgentPluginInputs[TProcedure]];

async function callAgentPluginProcedure<
  TProcedure extends AgentPluginProcedure,
>(
  window: Page,
  procedure: TProcedure,
  type: AgentPluginOperation<TProcedure>,
  ...inputArguments: AgentPluginInputArguments<TProcedure>
): Promise<AgentPluginOutputs[TProcedure]> {
  const input = inputArguments[0];
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
    { input, path: `agentPlugins.${procedure}`, type },
  ) as Promise<AgentPluginOutputs[TProcedure]>;
}

test.describe("Agent Plugins", () => {
  test("registers skill and MCP metadata through Electron IPC", async ({
    electronApp,
    window,
  }) => {
    const e2eHome = await electronApp.evaluate(({ app }) =>
      app.getPath("home"),
    );
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
      path.join(pluginDirectory, "mcp.json"),
      `${JSON.stringify({
        $schema: MCP_SCHEMA,
        mcpServers: {
          "remote-tools": {
            type: "streamable-http",
            url: "https://example.com/mcp",
          },
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
      expect.objectContaining({
        name: "remote-tools",
        type: "streamable-http",
        approval: "not-required",
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
      expect.objectContaining({
        name: "remote-tools",
        type: "streamable-http",
        approval: "not-required",
      }),
    ]);

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
