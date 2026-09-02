import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { unzipSync } from "fflate";
import { defineConfig } from "tsup";
import { HARNESS_EXTENSION_ENTRYPOINTS } from "./src/extensions/entrypoints";

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
    ...Object.values(HARNESS_EXTENSION_ENTRYPOINTS).map(
      (entrypoint) => `src/extensions/${entrypoint}.ts`,
    ),
    "src/extensions/auto-publish/index.ts",
    "src/extensions/posthog-provider/model-catalog.ts",
    "src/extensions/mcp/config.ts",
    "src/extensions/mcp/schema.ts",
    "src/extensions/footer-focus-demo/index.ts",
  ],
  format: ["esm"],
  dts: false,
  sourcemap: true,
  clean: true,
  splitting: false,
  outDir: "dist",
  target: "node20",
  async onSuccess() {
    await cp(
      "src/extensions/orchestration/skills",
      "dist/extensions/orchestration/skills",
      { recursive: true },
    );
    await cp(
      "src/extensions/orchestration/bundled-agents",
      "dist/extensions/orchestration/bundled-agents",
      { recursive: true },
    );
    await cp("src/extensions/mcp/skills", "dist/extensions/mcp/skills", {
      recursive: true,
    });
    if (process.env.SKIP_PRODUCT_ENGINEER_SKILLS_DOWNLOAD !== "1") {
      await copyOmnibusSkills("dist/extensions/product-engineer/skills");
    }
  },
});
