import {
  chmodSync,
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  writeFileSync,
} from "node:fs";
import { builtinModules } from "node:module";
import { dirname, resolve } from "node:path";
import { defineConfig } from "tsup";
// Plain ESM helper, shared with apps/code/vite-main-plugins.mts.
import {
  CLAUDE_CLI_SUPPORT_DIRS,
  CLAUDE_CLI_SUPPORT_FILES,
  claudeBinName,
  claudeExecutableCandidates,
  targetArch,
  targetPlatform,
} from "./build/native-binary.mjs";

function nativeBinarySourcePath(): string | undefined {
  const candidates = claudeExecutableCandidates(
    resolve(import.meta.dirname, "../../node_modules"),
  );
  return candidates.find((p: string) => existsSync(p));
}

function copyClaudeSupportAssets(sourcePath: string, destDir: string): void {
  const sourceDir = dirname(sourcePath);

  for (const file of CLAUDE_CLI_SUPPORT_FILES) {
    const source = resolve(sourceDir, file);
    if (existsSync(source)) {
      copyFileSync(source, resolve(destDir, file));
    }
  }

  for (const dir of CLAUDE_CLI_SUPPORT_DIRS) {
    const source = resolve(sourceDir, dir);
    if (existsSync(source)) {
      cpSync(source, resolve(destDir, dir), { recursive: true });
    }
  }
}

function copyAssets() {
  const distDir = resolve(import.meta.dirname, "dist");
  const templatesDir = resolve(distDir, "templates");
  const claudeCliDir = resolve(distDir, "claude-cli");

  mkdirSync(templatesDir, { recursive: true });
  mkdirSync(claudeCliDir, { recursive: true });

  const srcTemplatesDir = resolve(import.meta.dirname, "src/templates");
  if (existsSync(srcTemplatesDir)) {
    cpSync(srcTemplatesDir, templatesDir, { recursive: true });
  }

  const binName = claudeBinName();
  const nativeBinary = nativeBinarySourcePath();
  if (nativeBinary) {
    const dest = resolve(claudeCliDir, binName);
    copyFileSync(nativeBinary, dest);
    if (targetPlatform() !== "win32") {
      chmodSync(dest, 0o755);
    }
    copyClaudeSupportAssets(nativeBinary, claudeCliDir);
  } else {
    console.warn(
      `[agent/tsup] No Claude executable found for ${targetPlatform()}-${targetArch()}; install @anthropic-ai/claude-agent-sdk optional deps`,
    );
  }

  writeFileSync(
    resolve(claudeCliDir, "package.json"),
    JSON.stringify({ type: "module" }, null, 2),
  );
}

const sharedOptions = {
  sourcemap: true,
  splitting: false,
  outDir: "dist",
  target: "node20",
  noExternal: [
    "@posthog/shared",
    "@posthog/git",
    "@posthog/enricher",
    "@posthog/harness",
    /^@opentelemetry\//,
    "fflate",
  ],
  external: [
    ...builtinModules,
    ...builtinModules.map((m) => `node:${m}`),
    "@agentclientprotocol/sdk",
    "@anthropic-ai/claude-agent-sdk",
    "dotenv",
    "openai",
    "tar",
    "zod",
  ],
};

export default defineConfig([
  {
    entry: [
      "src/index.ts",
      "src/acp-extensions.ts",
      "src/agent.ts",
      "src/gateway-models.ts",
      "src/handoff-checkpoint.ts",
      "src/posthog-api.ts",
      "src/posthog-products.ts",
      "src/pr-url-detector.ts",
      "src/pi/rpc-client.ts",
      "src/pi/runtime.ts",
      "src/pi/types.ts",
      "src/pi/conversation/translatePiConversation.ts",
      "src/resume.ts",
      "src/types.ts",
      "src/adapters/claude/questions/utils.ts",
      "src/adapters/claude/permissions/permission-options.ts",
      "src/adapters/claude/tools.ts",
      "src/adapters/claude/conversion/tool-use-to-acp.ts",
      "src/adapters/claude/session/jsonl-hydration.ts",
      "src/adapters/claude/session/mcp-config.ts",
      "src/adapters/claude/session/models.ts",
      "src/adapters/codex-app-server/models.ts",
      "src/adapters/codex-app-server/local-tools-mcp-server.ts",
      "src/adapters/claude/mcp/tool-metadata.ts",
      "src/adapters/reasoning-effort.ts",
      "src/execution-mode.ts",
      "src/server/schemas.ts",
      "src/server/agent-server.ts",
    ],
    format: ["esm"],
    dts: false,
    clean: false,
    // noExternal inlines CJS deps (e.g. simple-git via @posthog/git) whose
    // dynamic `require(...)` calls throw in ESM output unless a real require
    // exists. Entries spawned directly by node (local-tools-mcp-server.js)
    // crash at import time without this shim.
    banner: {
      js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
    },
    ...sharedOptions,
    onSuccess: async () => {
      copyAssets();
      console.log("Assets copied successfully");

      // Touch a trigger file to signal electron-forge to restart
      // This file is watched by Vite, triggering main process rebuild
      // Skip in Docker/CI environments where the code app doesn't exist
      const triggerFile = resolve(
        import.meta.dirname,
        "../../apps/code/src/main/.agent-trigger",
      );
      const triggerDir = resolve(
        import.meta.dirname,
        "../../apps/code/src/main",
      );
      if (existsSync(triggerDir)) {
        writeFileSync(triggerFile, `${Date.now()}`);
      }
    },
  },
  {
    entry: { "server/bin": "src/server/bin.ts" },
    format: ["cjs"],
    dts: false,
    clean: false,
    ...sharedOptions,
  },
  {
    entry: { "pi/rpc-host": "src/pi/rpc-host.ts" },
    format: ["esm"],
    dts: false,
    clean: false,
    banner: {
      js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
    },
    ...sharedOptions,
    noExternal: [/^(?!node:)/],
    external: [...builtinModules, ...builtinModules.map((m) => `node:${m}`)],
  },
]);
