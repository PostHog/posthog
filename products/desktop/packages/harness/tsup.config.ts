import { cp } from "node:fs/promises";
import { defineConfig } from "tsup";

export default defineConfig({
  entry: [
    "src/index.ts",
    "src/cli.ts",
    "src/runtime.ts",
    "src/extensions/registry.ts",
    "src/extensions/hog-branding/extension.ts",
    "src/extensions/hog-branding/index.ts",
    "src/extensions/posthog-provider/extension.ts",
    "src/extensions/posthog-provider/index.ts",
    "src/extensions/posthog-provider/provider.ts",
    "src/extensions/posthog-provider/models.ts",
    "src/extensions/posthog-provider/oauth.ts",
    "src/extensions/posthog-provider/gateway.ts",
    "src/extensions/posthog-provider/gateway-auth.ts",
    "src/extensions/background-jobs/extension.ts",
    "src/extensions/background-jobs/index.ts",
    "src/extensions/background-jobs/jobs.ts",
    "src/extensions/background-jobs/render.ts",
    "src/extensions/web-access/extension.ts",
    "src/extensions/web-access/index.ts",
    "src/extensions/web-access/web-search.ts",
    "src/extensions/web-access/web-fetch.ts",
    "src/extensions/subagent/extension.ts",
    "src/extensions/subagent/index.ts",
    "src/extensions/subagent/agents.ts",
    "src/extensions/subagent/discovery.ts",
    "src/extensions/subagent/settings.ts",
    "src/extensions/subagent/policy.ts",
    "src/extensions/subagent/auth.ts",
    "src/extensions/subagent/context.ts",
    "src/extensions/subagent/process/child-process.ts",
    "src/extensions/subagent/process/pi-subprocess.ts",
    "src/extensions/subagent/run-agent.ts",
    "src/extensions/subagent/process/pool.ts",
    "src/extensions/subagent/lifecycle.ts",
    "src/extensions/subagent/render.ts",
    "src/extensions/subagent/text-truncate.ts",
    "src/extensions/subagent/format.ts",
    "src/extensions/subagent/status-registry.ts",
    "src/extensions/subagent/status-footer.ts",
    "src/extensions/subagent/status-editor.ts",
    "src/extensions/subagent/status-overlay.ts",
    "src/extensions/workflow/extension.ts",
    "src/extensions/workflow/index.ts",
    "src/extensions/workflow/runtime.ts",
    "src/extensions/workflow/render.ts",
    "src/extensions/workflow/status-registry.ts",
    "src/extensions/workflow/status-overlay.ts",
    "src/extensions/mcp/extension.ts",
    "src/extensions/mcp/index.ts",
    "src/extensions/mcp/config.ts",
    "src/extensions/mcp/errors.ts",
    "src/extensions/mcp/schema.ts",
    "src/extensions/mcp/server-manager.ts",
    "src/extensions/mcp/tool-bridge.ts",
    "src/extensions/mcp/auth-storage.ts",
    "src/extensions/mcp/oauth-provider.ts",
    "src/extensions/mcp/callback-server.ts",
    "src/extensions/mcp/auth-flow.ts",
    "src/extensions/mcp/render.ts",
    "src/extensions/footer-focus-demo/extension.ts",
    "src/extensions/footer-focus-demo/index.ts",
    "src/extensions/footer-focus-demo/inbox.ts",
    "src/extensions/footer-focus-demo/footer.ts",
    "src/extensions/footer-focus-demo/editor.ts",
    "src/extensions/footer-focus-demo/overlay.ts",
  ],
  format: ["esm"],
  dts: false,
  sourcemap: true,
  clean: true,
  splitting: false,
  outDir: "dist",
  target: "node20",
  async onSuccess() {
    // The bundled skill and the bundled agent definitions are static data (no
    // compilation needed), but they must land next to the compiled subagent
    // extension so `resources_discover`'s and `agents.ts`'s
    // `import.meta.url`-relative paths find them at runtime.
    await cp(
      "src/extensions/subagent/skills",
      "dist/extensions/subagent/skills",
      {
        recursive: true,
      },
    );
    await cp(
      "src/extensions/subagent/bundled-agents",
      "dist/extensions/subagent/bundled-agents",
      {
        recursive: true,
      },
    );
    await cp("src/extensions/mcp/skills", "dist/extensions/mcp/skills", {
      recursive: true,
    });
    await cp(
      "src/extensions/workflow/skills",
      "dist/extensions/workflow/skills",
      { recursive: true },
    );
    // The workflow extension imports `../subagent/agents`, and tsup
    // (splitting: false) inlines that module into workflow's own bundle — so
    // its `import.meta.url`-relative `./bundled-agents` lookup resolves under
    // dist/extensions/workflow/, not dist/extensions/subagent/. Any bundle
    // that inlines agents.ts needs its own copy of the asset directory.
    await cp(
      "src/extensions/subagent/bundled-agents",
      "dist/extensions/workflow/bundled-agents",
      { recursive: true },
    );
  },
});
