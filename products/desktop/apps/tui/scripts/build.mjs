import { cpSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

// Bundles the TUI into dist/, so `posthog-tui` starts without Vite: one file for the app, and beside it the pi
// harness the agent spawns (rpc-host.js) with its skills, which the agent finds relative to its own module.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const agentDist = resolve(
  root,
  "../../../../packages/agent/packages/agent/dist",
);
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

// The desktop app's analytics key, baked in like the desktop's own build; the published bundle has no .env beside it.
const apiKey =
  process.env.VITE_POSTHOG_API_KEY ??
  (() => {
    try {
      return readFileSync(resolve(root, "../../.env"), "utf8").match(
        /^VITE_POSTHOG_API_KEY=(\S+)/m,
      )?.[1];
    } catch {
      return undefined;
    }
  })();

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

await build({
  entryPoints: [join(root, "src/main.tsx")],
  outfile: join(dist, "posthog-tui.mjs"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node22",
  jsx: "automatic",
  // No sourcemap: it doubles the published size, and the bundle is read in the repo, not from node_modules.
  sourcemap: false,
  logLevel: "warning",
  // pi reads its themes and config from files beside its own modules, so it stays a dependency on disk.
  external: ["@earendil-works/*"],
  define: {
    "process.env.NODE_ENV": '"production"',
    "import.meta.hot": "undefined",
    ...(apiKey && {
      "process.env.VITE_POSTHOG_API_KEY": JSON.stringify(apiKey),
    }),
  },
  // Bundled packages use require() for node builtins and import.meta.url for files beside them.
  banner: {
    js: [
      'import { createRequire as __tuiCreateRequire } from "node:module";',
      "const require = __tuiCreateRequire(import.meta.url);",
    ].join("\n"),
  },
});

// A release build must carry the analytics key; a local build without one just sends nothing.
if (process.env.CI && !apiKey) {
  console.error(
    "VITE_POSTHOG_API_KEY is not set, so this build would send no analytics",
  );
  process.exit(1);
}

cpSync(join(agentDist, "pi/rpc-host.js"), join(dist, "rpc-host.js"));
cpSync(join(agentDist, "pi/skills"), join(dist, "skills"), { recursive: true });
// The pi host builds a local-tools MCP server for every local chat and looks for its script within a few
// folders of the bundle; the enricher looks for its grammars beside the bundle the same way.
cpSync(
  join(agentDist, "adapters/codex-app-server/local-tools-mcp-server.js"),
  join(dist, "adapters/codex-app-server/local-tools-mcp-server.js"),
);
cpSync(join(agentDist, "grammars"), join(dist, "grammars"), {
  recursive: true,
});
console.log(`Built ${pkg.name}@${pkg.version} into ${dist}`);
