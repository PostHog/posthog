import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RpcClient } from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import {
  createPiRpcClient,
  createRuntimeMcpServers,
  createRuntimeMcpStdioServers,
} from "./rpc-client";
import type { TaskContext } from "./task-system-prompt";

function taskContext(cwd: string): TaskContext {
  return {
    taskId: "task-1",
    cwd,
    projectId: 2,
    apiHost: "https://us.posthog.com",
    environment: "local",
  };
}

describe("createRuntimeMcpServers", () => {
  it("maps agent-server HTTP and SSE servers to Harness configuration", () => {
    expect(
      createRuntimeMcpServers([
        {
          name: "posthog",
          type: "http",
          url: "https://mcp.example/mcp",
          headers: [{ name: "authorization", value: "Bearer token" }],
        },
        {
          name: "legacy",
          type: "sse",
          url: "https://mcp.example/sse",
          headers: [],
        },
      ]),
    ).toMatchObject({
      posthog: {
        transport: "streamable-http",
        url: "https://mcp.example/mcp",
        headers: { authorization: "Bearer token" },
      },
      legacy: {
        transport: "sse",
        url: "https://mcp.example/sse",
      },
    });
  });

  it("maps local tools to an eager direct stdio server", () => {
    expect(
      createRuntimeMcpStdioServers([
        {
          name: "posthog-code-tools",
          command: process.execPath,
          args: ["local-tools-mcp-server.js"],
          env: [{ name: "POSTHOG_LOCAL_TOOLS_ENABLED", value: "finish" }],
        },
      ]),
    ).toEqual({
      "posthog-code-tools": {
        command: process.execPath,
        args: ["local-tools-mcp-server.js"],
        env: { POSTHOG_LOCAL_TOOLS_ENABLED: "finish" },
        transport: "stdio",
        lifecycle: "eager",
        requestTimeoutMs: 300_000,
        directTools: true,
      },
    });
  });
});

describe("createPiRpcClient", () => {
  it("does not put provider credentials in the child environment", () => {
    const client = createPiRpcClient({
      taskContext: taskContext("/workspace"),
      model: "claude-opus-4-8",
      providerOptions: {
        region: "us",
        baseUrl: "http://127.0.0.1:1234",
        apiKey: "proxy-key",
      },
    });

    expect(client).toBeInstanceOf(RpcClient);
    expect(client).toMatchObject({
      options: {
        cwd: "/workspace",
        model: "claude-opus-4-8",
        provider: "posthog",
      },
    });
    expect(
      (client as unknown as { options: { env?: Record<string, string> } })
        .options.env,
    ).toBeUndefined();
  });

  it("passes repository trust over the private bootstrap pipe", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-project-trust-"));
    const hostPath = join(directory, "host.mjs");
    const capturePath = join(directory, "bootstrap.json");
    await writeFile(
      hostPath,
      `
import { readFileSync, writeFileSync } from "node:fs";

writeFileSync(${JSON.stringify(capturePath)}, readFileSync(3, "utf8"));
process.stdin.resume();
`,
    );
    const client = createPiRpcClient({
      cliPath: hostPath,
      taskContext: taskContext(directory),
      projectTrusted: true,
      extensions: ["auto-publish"],
      providerOptions: { apiKey: "proxy-key" },
      enrichment: {
        apiUrl: "http://127.0.0.1:5678",
        publicApiUrl: "https://us.posthog.com",
        projectId: 2,
        apiKey: "enrichment-proxy-key",
      },
    });

    try {
      await client.start();
      await vi.waitFor(async () => {
        await expect(readFile(capturePath, "utf8")).resolves.toBe(
          JSON.stringify({
            providerOptions: { apiKey: "proxy-key" },
            enrichment: {
              apiUrl: "http://127.0.0.1:5678",
              publicApiUrl: "https://us.posthog.com",
              projectId: 2,
              apiKey: "enrichment-proxy-key",
            },
            projectTrusted: true,
            taskContext: taskContext(directory),
            extensions: ["auto-publish"],
          }),
        );
      });
    } finally {
      await client.stop();
      await rm(directory, { recursive: true });
    }
  });

  it("passes requested extensions privately and enables Electron's Node mode", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-electron-node-mode-"));
    const hostPath = join(directory, "host.mjs");
    const capturePath = join(directory, "capture.txt");
    await writeFile(
      hostPath,
      `
import { closeSync, readFileSync, writeFileSync } from "node:fs";

const bootstrap = JSON.parse(readFileSync(3, "utf8"));
closeSync(3);
writeFileSync(${JSON.stringify(capturePath)}, JSON.stringify({
  nodeMode: process.env.ELECTRON_RUN_AS_NODE ?? "",
  extensions: bootstrap.extensions,
  apiKey: bootstrap.providerOptions.apiKey,
}));
process.stdin.resume();
`,
    );
    const client = createPiRpcClient({
      cliPath: hostPath,
      taskContext: taskContext(directory),
      providerOptions: { apiKey: "proxy-key" },
      extensions: ["repository-tools"],
    });

    try {
      await client.start();
      await vi.waitFor(async () => {
        await expect(readFile(capturePath, "utf8")).resolves.toBe(
          JSON.stringify({
            nodeMode: "1",
            extensions: ["repository-tools"],
            apiKey: "proxy-key",
          }),
        );
      });
    } finally {
      await client.stop();
      await rm(directory, { recursive: true });
    }
  });

  it("intercepts extension UI requests and writes responses on the Pi wire", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-extension-ui-"));
    const hostPath = join(directory, "host.mjs");
    const capturePath = join(directory, "response.json");
    await writeFile(
      hostPath,
      `
import { closeSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";

closeSync(3);
process.stdout.write(JSON.stringify({
  type: "extension_ui_request",
  id: "extension-1",
  method: "input",
  title: "Your name",
}) + "\\n");
createInterface({ input: process.stdin }).on("line", (line) => {
  writeFileSync(${JSON.stringify(capturePath)}, line);
});
`,
    );
    const client = createPiRpcClient({
      cliPath: hostPath,
      taskContext: taskContext(directory),
      providerOptions: { apiKey: "proxy-key" },
    });
    const request = new Promise<unknown>((resolve) => client.onEvent(resolve));

    try {
      await client.start();
      await expect(request).resolves.toEqual({
        type: "extension_ui_request",
        id: "extension-1",
        method: "input",
        title: "Your name",
      });
      await client.respondToExtensionUI({
        type: "extension_ui_response",
        id: "extension-1",
        value: "Ada",
      });
      await vi.waitFor(async () => {
        await expect(readFile(capturePath, "utf8")).resolves.toBe(
          JSON.stringify({
            type: "extension_ui_response",
            id: "extension-1",
            value: "Ada",
          }),
        );
      });
    } finally {
      await client.stop();
      await rm(directory, { recursive: true });
    }
  });

  it("passes runtime MCP servers through the bootstrap channel", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-runtime-mcp-"));
    const hostPath = join(directory, "host.mjs");
    const capturePath = join(directory, "capture.json");
    await writeFile(
      hostPath,
      `
import { readFileSync, writeFileSync } from "node:fs";

writeFileSync(${JSON.stringify(capturePath)}, readFileSync(3, "utf8"));
process.stdin.resume();
`,
    );
    const client = createPiRpcClient({
      cliPath: hostPath,
      taskContext: taskContext(directory),
      providerOptions: { apiKey: "proxy-key" },
      runtimeMcpServers: {
        posthog: {
          args: [],
          directTools: false,
          lifecycle: "lazy",
          transport: "streamable-http",
          url: "http://127.0.0.1:4321/posthog",
        },
      },
    });

    try {
      await client.start();
      await vi.waitFor(async () => {
        await expect(readFile(capturePath, "utf8")).resolves.toContain(
          '"runtimeMcpServers"',
        );
      });
    } finally {
      await client.stop();
      await rm(directory, { recursive: true });
    }
  });

  it("routes MCP permission requests over the private host channel", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-mcp-permission-"));
    const hostPath = join(directory, "host.mjs");
    const capturePath = join(directory, "capture.json");
    await writeFile(
      hostPath,
      `
import { closeSync, writeFileSync } from "node:fs";

closeSync(3);
process.stdin.resume();
process.send({
  type: "posthog_pi_mcp_permission_request",
  request: {
    requestId: "call-1",
    serverName: "Cloudflare",
    toolName: "search",
    installationId: "installation-1",
    arguments: { query: "workers" },
  },
});
process.on("message", (response) => {
  if (response.type === "posthog_pi_mcp_permission_response") {
    writeFileSync(${JSON.stringify(capturePath)}, JSON.stringify(response));
  }
});
`,
    );
    const requestMcpToolPermission = vi.fn();
    const client = createPiRpcClient({
      cliPath: hostPath,
      taskContext: taskContext(directory),
      providerOptions: { apiKey: "proxy-key" },
    });
    client.onMcpToolPermissionRequest((request) => {
      requestMcpToolPermission(request);
      client.respondMcpToolPermission(request.requestId, "allow");
    });

    try {
      await client.start();
      await vi.waitFor(async () => {
        await expect(readFile(capturePath, "utf8")).resolves.toContain(
          '"decision":"allow"',
        );
      });
      expect(requestMcpToolPermission).toHaveBeenCalledWith(
        expect.objectContaining({ requestId: "call-1" }),
      );
    } finally {
      await client.stop();
      await rm(directory, { recursive: true });
    }
  });

  it("uses the private host channel without changing Pi RPC", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-host-channel-"));
    const hostPath = join(directory, "host.mjs");
    await writeFile(
      hostPath,
      `
import { closeSync } from "node:fs";

closeSync(3);
process.stdin.resume();
process.on("message", (request) => {
  const data = request.method === "clear_queue"
    ? { steering: ["cleared"], followUp: [] }
    : { steering: ["queued"], followUp: ["later"] };
  process.send({ type: "posthog_pi_host_response", id: request.id, data });
});
`,
    );
    const client = createPiRpcClient({
      cliPath: hostPath,
      taskContext: taskContext(directory),
      providerOptions: { apiKey: "proxy-key" },
    });

    try {
      await client.start();

      await expect(client.getQueue()).resolves.toEqual({
        steering: ["queued"],
        followUp: ["later"],
      });
      await expect(client.clearQueue()).resolves.toEqual({
        steering: ["cleared"],
        followUp: [],
      });
    } finally {
      await client.stop();
      await rm(directory, { recursive: true });
    }
  });
});
