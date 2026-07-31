import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RpcClient } from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import { createPiRpcClient, createRuntimeMcpServers } from "./rpc-client";

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
});

describe("createPiRpcClient", () => {
  it("does not put provider credentials in the child environment", () => {
    const client = createPiRpcClient({
      cwd: "/workspace",
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

  it("runs the RPC host with Electron's Node mode enabled", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-electron-node-mode-"));
    const hostPath = join(directory, "host.mjs");
    const capturePath = join(directory, "capture.txt");
    await writeFile(
      hostPath,
      `
import { closeSync, writeFileSync } from "node:fs";

closeSync(3);
writeFileSync(${JSON.stringify(capturePath)}, process.env.ELECTRON_RUN_AS_NODE ?? "");
process.stdin.resume();
`,
    );
    const client = createPiRpcClient({
      cliPath: hostPath,
      cwd: directory,
      providerOptions: { apiKey: "proxy-key" },
    });

    try {
      await client.start();
      await vi.waitFor(async () => {
        await expect(readFile(capturePath, "utf8")).resolves.toBe("1");
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
      cwd: directory,
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
      cwd: directory,
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
      cwd: directory,
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
