import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { unzipSync } from "fflate";
import { defineConfig } from "tsup";

const CONTEXT_MILL_SKILLS_URL =
  "https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip";

function safeArchivePath(archivePath: string): string | null {
  const normalizedPath = archivePath.replaceAll("\\", "/");
  const segments = normalizedPath.split("/");
  if (
    normalizedPath.startsWith("/") ||
    normalizedPath.endsWith("/") ||
    segments.some((segment) => !segment || segment === "." || segment === "..")
  ) {
    return null;
  }
  return normalizedPath;
}

async function copyOmnibusSkills(targetDirectory: string): Promise<void> {
  const response = await fetch(CONTEXT_MILL_SKILLS_URL, {
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    throw new Error(
      `Failed to download context-mill skills: ${response.status} ${response.statusText}`,
    );
  }

  await rm(targetDirectory, { recursive: true, force: true });
  await mkdir(targetDirectory, { recursive: true });

  const outerEntries = unzipSync(new Uint8Array(await response.arrayBuffer()));
  let copiedSkills = 0;
  for (const [archivePath, archiveContent] of Object.entries(outerEntries)) {
    const archiveName = archivePath.replaceAll("\\", "/").split("/").at(-1);
    if (!archiveName?.startsWith("omnibus-") || !archiveName.endsWith(".zip")) {
      continue;
    }

    const skillName = archiveName.slice("omnibus-".length, -".zip".length);
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(skillName)) {
      continue;
    }

    const skillDirectory = join(targetDirectory, skillName);
    await mkdir(skillDirectory, { recursive: true });
    const innerEntries = unzipSync(new Uint8Array(archiveContent));
    for (const [innerPath, innerContent] of Object.entries(innerEntries)) {
      const relativePath = safeArchivePath(innerPath);
      if (!relativePath) {
        continue;
      }

      const outputPath = join(skillDirectory, relativePath);
      await mkdir(dirname(outputPath), { recursive: true });
      if (relativePath.split("/").at(-1) === "SKILL.md") {
        const skill = new TextDecoder()
          .decode(innerContent)
          .replace(/^(name:\s*)omnibus-/m, "$1");
        await writeFile(outputPath, skill);
      } else {
        await writeFile(outputPath, innerContent);
      }
    }
    copiedSkills += 1;
  }

  if (copiedSkills === 0) {
    throw new Error("No omnibus skills found in the context-mill release");
  }
}

export default defineConfig({
  entry: [
    "src/index.ts",
    "src/cli.ts",
    "src/runtime.ts",
    "src/project-trust.ts",
    "src/extensions/registry.ts",
    "src/extensions/auto-publish/extension.ts",
    "src/extensions/auto-publish/index.ts",
    "src/extensions/hog-branding/extension.ts",
    "src/extensions/hog-branding/index.ts",
    "src/extensions/posthog-provider/extension.ts",
    "src/extensions/posthog-provider/index.ts",
    "src/extensions/posthog-provider/provider.ts",
    "src/extensions/posthog-provider/models.ts",
    "src/extensions/posthog-provider/model-catalog.ts",
    "src/extensions/posthog-provider/oauth.ts",
    "src/extensions/posthog-provider/gateway.ts",
    "src/extensions/posthog-provider/gateway-auth.ts",
    "src/extensions/product-engineer/extension.ts",
    "src/extensions/product-engineer/index.ts",
    "src/extensions/posthog-mcp-policy/extension.ts",
    "src/extensions/posthog-mcp-policy/index.ts",
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
    if (process.env.SKIP_PRODUCT_ENGINEER_SKILLS_DOWNLOAD !== "1") {
      await copyOmnibusSkills("dist/extensions/product-engineer/skills");
    }
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
