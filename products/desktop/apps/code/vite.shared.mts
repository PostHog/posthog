import path from "node:path";
import { fileURLToPath } from "node:url";
import posthog from "@posthog/rollup-plugin";
import type { Alias, Plugin } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function createPosthogPlugin(
  env: Record<string, string>,
  project: string,
): Plugin | null {
  if (!env.POSTHOG_SOURCEMAP_API_KEY || !env.POSTHOG_ENV_ID) {
    return null;
  }
  return posthog({
    personalApiKey: env.POSTHOG_SOURCEMAP_API_KEY,
    projectId: env.POSTHOG_ENV_ID,
    host: env.POSTHOG_HOST,
    sourcemaps: {
      releaseName: project,
      deleteAfterUpload: true,
    },
  });
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
