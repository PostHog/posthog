import path from "node:path";
import { fileURLToPath } from "node:url";
import posthog from "@posthog/rollup-plugin";
import type { Alias, Plugin } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// The plugin uploads sourcemaps in its writeBundle hook by shelling out to
// posthog-cli. When that upload times out the CLI exits non-zero, the hook
// rejects, and the whole `electron-vite build` fails — which used to sink the
// desktop release on a single flaky network round trip. Retry the upload a few
// times, then, if it still fails, warn and let the build continue: a signed,
// shippable app matters more than a sourcemap upload, and error symbolication
// for one release degrades gracefully rather than blocking the ship.
const SOURCEMAP_UPLOAD_ATTEMPTS = 3;
const SOURCEMAP_UPLOAD_BACKOFF_MS = [10_000, 20_000];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function withResilientSourcemapUpload(plugin: Plugin): Plugin {
  const hook = plugin.writeBundle;
  if (!hook || typeof hook !== "object" || typeof hook.handler !== "function") {
    return plugin;
  }
  const originalHandler = hook.handler as (
    this: unknown,
    ...args: unknown[]
  ) => unknown;
  return {
    ...plugin,
    writeBundle: {
      ...hook,
      async handler(this: unknown, ...args: unknown[]): Promise<unknown> {
        for (let attempt = 1; attempt <= SOURCEMAP_UPLOAD_ATTEMPTS; attempt++) {
          try {
            return await originalHandler.apply(this, args);
          } catch (error) {
            if (attempt >= SOURCEMAP_UPLOAD_ATTEMPTS) {
              console.warn(
                `[posthog] sourcemap upload failed after ${SOURCEMAP_UPLOAD_ATTEMPTS} attempts; shipping build without uploaded sourcemaps. Last error: ${error}`,
              );
              return undefined;
            }
            const wait = SOURCEMAP_UPLOAD_BACKOFF_MS[attempt - 1] ?? 20_000;
            console.warn(
              `[posthog] sourcemap upload failed (attempt ${attempt}/${SOURCEMAP_UPLOAD_ATTEMPTS}), retrying in ${wait / 1000}s: ${error}`,
            );
            await delay(wait);
          }
        }
        return undefined;
      },
    },
  } as Plugin;
}

export function createPosthogPlugin(
  env: Record<string, string>,
  project: string,
): Plugin | null {
  if (!env.POSTHOG_SOURCEMAP_API_KEY || !env.POSTHOG_ENV_ID) {
    return null;
  }
  return withResilientSourcemapUpload(
    posthog({
      personalApiKey: env.POSTHOG_SOURCEMAP_API_KEY,
      projectId: env.POSTHOG_ENV_ID,
      host: env.POSTHOG_HOST,
      sourcemaps: {
        releaseName: project,
        deleteAfterUpload: true,
      },
    }),
  );
}

export function createForceDevModeDefine(): Record<string, string> | undefined {
  if (process.env.FORCE_DEV_MODE !== "1") {
    return undefined;
  }
  return {
    "import.meta.env.DEV": "true",
    "import.meta.env.PROD": "false",
    "import.meta.env.MODE": '"development"',
  };
}

const baseAliases: Alias[] = [
  { find: "@main", replacement: path.resolve(__dirname, "./src/main") },
  { find: "@renderer", replacement: path.resolve(__dirname, "./src/renderer") },
  { find: "@shared", replacement: path.resolve(__dirname, "./src/shared") },
];

export const workspaceAliases: Alias[] = [
  {
    find: /^@posthog\/agent\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/agent/src/$1.ts"),
  },
  {
    find: "@posthog/agent",
    replacement: path.resolve(__dirname, "../../packages/agent/src/index.ts"),
  },
  {
    find: /^@posthog\/shared\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/shared/src/$1"),
  },
  {
    find: "@posthog/shared",
    replacement: path.resolve(__dirname, "../../packages/shared/src/index.ts"),
  },
  {
    find: "@posthog/enricher",
    replacement: path.resolve(
      __dirname,
      "../../packages/enricher/src/index.ts",
    ),
  },
  {
    find: /^@posthog\/core\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/core/src/$1"),
  },
  {
    find: /^@posthog\/di\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/di/src/$1"),
  },
  {
    find: /^@posthog\/api-client\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/api-client/src/$1"),
  },
  {
    find: /^@posthog\/ui\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/ui/src/$1"),
  },
  {
    find: /^@posthog\/host-trpc\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/host-trpc/src/$1"),
  },
  {
    find: /^@posthog\/host-router\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/host-router/src/$1"),
  },
  {
    find: /^@posthog\/workspace-client\/(.+)$/,
    replacement: path.resolve(
      __dirname,
      "../../packages/workspace-client/src/$1",
    ),
  },
  {
    find: /^@posthog\/workspace-server\/(.+)$/,
    replacement: path.resolve(
      __dirname,
      "../../packages/workspace-server/src/$1",
    ),
  },
  {
    find: /^@posthog\/platform\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/platform/src/$1"),
  },
];

export const mainAliases: Alias[] = [
  ...baseAliases,
  {
    find: "@posthog/electron-trpc/main",
    replacement: path.resolve(
      __dirname,
      "../../packages/electron-trpc/src/main/index.ts",
    ),
  },
  {
    find: /^@posthog\/git\/(.+)$/,
    replacement: path.resolve(__dirname, "../../packages/git/src/$1"),
  },
  ...workspaceAliases,
];

export const rendererAliases: Alias[] = [
  ...baseAliases,
  {
    find: "@features",
    replacement: path.resolve(__dirname, "./src/renderer/features"),
  },
  {
    find: "@components",
    replacement: path.resolve(__dirname, "./src/renderer/components"),
  },
  {
    find: "@stores",
    replacement: path.resolve(__dirname, "./src/renderer/stores"),
  },
  {
    find: "@hooks",
    replacement: path.resolve(__dirname, "./src/renderer/hooks"),
  },
  {
    find: "@utils",
    replacement: path.resolve(__dirname, "./src/renderer/utils"),
  },
  {
    find: "@posthog/electron-trpc/renderer",
    replacement: path.resolve(
      __dirname,
      "../../packages/electron-trpc/src/renderer/index.ts",
    ),
  },
  ...workspaceAliases,
];
