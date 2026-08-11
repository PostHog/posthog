// This file has been automatically migrated to valid ESM format by Storybook.
import path, { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { StorybookConfig } from "@storybook/react-vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { mergeConfig } from "vite";
import { workspaceAliases } from "../vite.shared.mts";

const __filename = fileURLToPath(import.meta.url);

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function getAbsolutePath(value: string) {
  return dirname(fileURLToPath(import.meta.resolve(`${value}/package.json`)));
}

const config: StorybookConfig = {
  stories: [
    "../src/**/*.mdx",
    "../src/**/*.stories.@(js|jsx|mjs|ts|tsx)",
    "../../../packages/ui/src/**/*.mdx",
    "../../../packages/ui/src/**/*.stories.@(js|jsx|mjs|ts|tsx)",
  ],
  addons: [
    getAbsolutePath("@storybook/addon-a11y"),
    getAbsolutePath("@storybook/addon-docs"),
  ],
  framework: getAbsolutePath("@storybook/react-vite"),
  // Use the TypeScript-compiler docgen instead of the default Babel react-docgen.
  // The Babel parser chokes on the legacy Inversify decorators (`@injectable()`)
  // in the @posthog/core services that components pull in; the TS-based docgen
  // handles them and only inspects `.tsx` components.
  typescript: {
    reactDocgen: "react-docgen-typescript",
  },
  async viteFinal(config) {
    return mergeConfig(config, {
      plugins: [tailwindcss(), react()],
      resolve: {
        alias: [
          {
            find: "@main",
            replacement: path.resolve(__dirname, "../src/main"),
          },
          {
            find: "@renderer",
            replacement: path.resolve(__dirname, "../src/renderer"),
          },
          {
            find: "@shared",
            replacement: path.resolve(__dirname, "../src/shared"),
          },
          { find: "@api", replacement: path.resolve(__dirname, "../src/api") },
          {
            find: "@features",
            replacement: path.resolve(__dirname, "../src/renderer/features"),
          },
          {
            find: "@components",
            replacement: path.resolve(__dirname, "../src/renderer/components"),
          },
          {
            find: "@stores",
            replacement: path.resolve(__dirname, "../src/renderer/stores"),
          },
          {
            find: "@hooks",
            replacement: path.resolve(__dirname, "../src/renderer/hooks"),
          },
          {
            find: "@utils",
            replacement: path.resolve(__dirname, "../src/renderer/utils"),
          },
          { find: "@", replacement: path.resolve(__dirname, "../src") },
          // Keep @posthog/agent on its prebuilt, browser-safe dist bundle. These
          // must precede the workspace source aliases below so they win.
          {
            find: "@posthog/agent/adapters/claude/permissions/permission-options",
            replacement: path.resolve(
              __dirname,
              "../../../packages/agent/dist/adapters/claude/permissions/permission-options.js",
            ),
          },
          {
            find: "@posthog/agent/adapters/claude/conversion/tool-use-to-acp",
            replacement: path.resolve(
              __dirname,
              "../../../packages/agent/dist/adapters/claude/conversion/tool-use-to-acp.js",
            ),
          },
          {
            find: "@posthog/agent/adapters/claude/questions/utils",
            replacement: path.resolve(
              __dirname,
              "../../../packages/agent/dist/adapters/claude/questions/utils.js",
            ),
          },
          {
            find: "@posthog/electron-trpc/renderer",
            replacement: path.resolve(__dirname, "./mocks/electron-trpc.ts"),
          },
          // The agent dist bundles are Node-targeted: tsup opens every file
          // with a createRequire(import.meta.url) shim, and tool-use-to-acp
          // imports fs/path. Shim those builtins so the bundles load in the
          // browser (see mocks/node-module.ts).
          {
            find: /^(node:)?module$/,
            replacement: path.resolve(__dirname, "./mocks/node-module.ts"),
          },
          {
            find: /^(node:)?fs$/,
            replacement: path.resolve(__dirname, "./mocks/node-fs.ts"),
          },
          { find: /^(node:)?path$/, replacement: "pathe" },
          // Resolve the remaining @posthog/* workspace packages to source, exactly
          // like the renderer (vite.shared.mts). Without this, Storybook resolves
          // them through each package's "./*" exports map, which only falls
          // through to ".ts" — so any ".tsx" subpath import (e.g. a feature view)
          // fails to resolve and the story 404s.
          ...workspaceAliases.filter((a) => !String(a.find).includes("agent")),
        ],
      },
    });
  },
};

export default config;
