// Post-build smoke check: boot the bundled local-tools MCP server exactly the
// way Codex spawns it in a cloud sandbox (a bare `node dist/...js` process) and
// assert it answers `tools/list`. Catches bundling regressions — e.g. inlined
// CJS deps whose dynamic `require()` throws in ESM output — that unit tests
// running from src can never see, and that otherwise fail silently in cloud
// runs (Codex drops a failed MCP server and the signed-git tools just vanish).
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const script = resolve(
  fileURLToPath(new URL(".", import.meta.url)),
  "../dist/adapters/codex-app-server/local-tools-mcp-server.js",
);

const ctx = Buffer.from(
  JSON.stringify({ cwd: "/tmp", taskId: "smoke", token: "smoke-token" }),
).toString("base64");

const child = spawn(process.execPath, [script], {
  env: {
    ...process.env,
    // Mirror the production Codex spawn: if this ever runs from an
    // Electron-hosted process, execPath is the app binary, not node.
    ELECTRON_RUN_AS_NODE: "1",
    POSTHOG_LOCAL_TOOLS_CTX: ctx,
    POSTHOG_LOCAL_TOOLS_ENABLED:
      "git_signed_commit,git_signed_merge,git_signed_rewrite",
  },
  stdio: ["pipe", "pipe", "pipe"],
});

let stderr = "";
child.stderr.on("data", (d) => {
  stderr += d.toString();
});

const timeout = setTimeout(() => {
  fail(`timed out waiting for tools/list response\nstderr: ${stderr}`);
}, 15_000);

function fail(message) {
  console.error(`[verify-local-tools-mcp-server] FAIL: ${message}`);
  child.kill();
  process.exit(1);
}

child.on("exit", (code) => {
  if (code !== null && code !== 0) {
    fail(
      `server exited with code ${code} before responding\nstderr: ${stderr}`,
    );
  }
});

child.stdin.write(
  `${JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "smoke", version: "0.0.0" },
    },
  })}\n`,
);
child.stdin.write(
  `${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`,
);
child.stdin.write(
  `${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" })}\n`,
);

let buffer = "";
child.stdout.on("data", (chunk) => {
  buffer += chunk.toString();
  let newline = buffer.indexOf("\n");
  while (newline >= 0) {
    const line = buffer.slice(0, newline).trim();
    buffer = buffer.slice(newline + 1);
    newline = buffer.indexOf("\n");
    if (!line) continue;
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      continue;
    }
    if (message.id !== 2) continue;
    const names = (message.result?.tools ?? []).map((t) => t.name);
    if (!names.includes("git_signed_commit")) {
      fail(
        `tools/list missing git_signed_commit, got: ${JSON.stringify(names)}`,
      );
    }
    console.log(
      `[verify-local-tools-mcp-server] OK: dist server boots and lists ${names.length} tools`,
    );
    clearTimeout(timeout);
    child.kill();
    process.exit(0);
  }
});
