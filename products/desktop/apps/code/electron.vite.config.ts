import { existsSync, readFileSync } from "node:fs";
import { builtinModules, createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { devtools as tanstackDevtools } from "@tanstack/devtools-vite";
import { TanStackRouterVite } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "electron-vite";
import { loadEnv } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";
import { buildExternals } from "./runtime-dependencies";
import {
  createForceDevModeDefine,
  createPosthogPlugin,
  mainAliases,
  rendererAliases,
} from "./vite.shared.mjs";
import {
  CONTEXT_MILL_ZIP_URL,
  copyClaudeExecutable,
  copyCodexAcpBinaries,
  copyDrizzleMigrations,
  copyEnricherGrammars,
  copyPiRpcHost,
  copyPosthogPlugin,
  fixFilenameCircularRef,
  getBuildDate,
  getGitCommit,
  SKILLS_ZIP_URL,
} from "./vite-main-plugins.mjs";
import { autoServicesPlugin } from "./vite-plugin-auto-services";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const pkg = JSON.parse(
  readFileSync(path.resolve(__dirname, "package.json"), "utf-8"),
);

const nodeExternals = [
  ...builtinModules,
  ...builtinModules.map((m) => `node:${m}`),
];

// Native .node modules can't be bundled — they stay external and resolve from
// the staged node_modules at runtime (see scripts/before-pack.ts).
const nativeModules = buildExternals;

const nearestPackageType = (fromFile: string): string | undefined => {
  let dir = path.dirname(fromFile);
  while (true) {
    const manifest = path.join(dir, "package.json");
    if (existsSync(manifest)) {
      try {
        return JSON.parse(readFileSync(manifest, "utf-8")).type;
      } catch {
        return undefined;
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) return undefined;
    dir = parent;
  }
};

const resolvesToCommonJs = (name: string): boolean => {
  let resolved: string;
  try {
    resolved = require.resolve(name);
  } catch {
    return false;
  }
  if (resolved.endsWith(".cjs")) return true;
  if (resolved.endsWith(".mjs")) return false;
  return nearestPackageType(resolved) !== "module";
};

const computeDevThirdPartyExternals = (): RegExp[] =>
  Object.keys(pkg.dependencies ?? {})
    .filter((name) => !name.startsWith("@posthog/") && resolvesToCommonJs(name))
    .map(
      (name) =>
        new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(/.+)?$`),
    );

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(__dirname, "../.."), "");
  const isDev = mode === "development";

  return {
    main: {
      plugins: [
        tsconfigPaths({ ignoreConfigErrors: true }),
        autoServicesPlugin(path.join(__dirname, "src/main/services")),
        fixFilenameCircularRef(),
        copyClaudeExecutable(),
        copyPiRpcHost(),
        copyPosthogPlugin(isDev),
        copyDrizzleMigrations(),
        copyCodexAcpBinaries(),
        copyEnricherGrammars(),
        createPosthogPlugin(env, "posthog-code-main"),
      ].filter(Boolean),
      define: {
        __BUILD_COMMIT__: JSON.stringify(getGitCommit()),
        __BUILD_DATE__: JSON.stringify(getBuildDate()),
        "process.env.VITE_POSTHOG_API_KEY": JSON.stringify(
          env.VITE_POSTHOG_API_KEY || "",
        ),
        "process.env.VITE_POSTHOG_API_HOST": JSON.stringify(
          env.VITE_POSTHOG_API_HOST || "",
        ),
        "process.env.VITE_POSTHOG_ACCESS_TOKEN_OVERRIDE": JSON.stringify(
          env.VITE_POSTHOG_ACCESS_TOKEN_OVERRIDE || "",
        ),
        "process.env.SKILLS_ZIP_URL": JSON.stringify(SKILLS_ZIP_URL),
        "process.env.CONTEXT_MILL_ZIP_URL":
          JSON.stringify(CONTEXT_MILL_ZIP_URL),
        ...createForceDevModeDefine(),
      },
      resolve: {
        alias: mainAliases,
        conditions: ["node"],
        mainFields: ["module", "jsnext:main", "jsnext"],
      },
      cacheDir: ".vite/cache",
      build: {
        outDir: path.join(__dirname, ".vite/build"),
        emptyOutDir: false,
        target: "node18",
        sourcemap: true,
        minify: false,
        reportCompressedSize: false,
        commonjsOptions: {
          transformMixedEsModules: true,
        },
        rollupOptions: {
          input: {
            bootstrap: path.resolve(__dirname, "src/main/bootstrap.ts"),
            "workspace-server": require.resolve(
              "@posthog/workspace-server/serve",
            ),
          },
          output: {
            format: "cjs",
            entryFileNames: "[name].js",
            // Flat chunk layout (no chunks/ subdir) so the main code's runtime
            // __dirname stays .vite/build, where the spawned workspace-server.js
            // child and its shared chunks are resolved from.
            chunkFileNames: "[name]-[hash].js",
          },
          external: [
            "electron",
            "electron/main",
            ...nodeExternals,
            ...nativeModules,
            ...(isDev ? computeDevThirdPartyExternals() : []),
          ],
          onwarn(warning, warn) {
            if (warning.code === "UNUSED_EXTERNAL_IMPORT") return;
            if (
              warning.code === "EVAL" &&
              warning.id?.includes("web-tree-sitter")
            )
              return;
            warn(warning);
          },
        },
      },
    },

    preload: {
      plugins: [tsconfigPaths({ ignoreConfigErrors: true })],
      resolve: {
        conditions: ["node"],
        mainFields: ["module", "jsnext:main", "jsnext"],
      },
      build: {
        outDir: path.join(__dirname, ".vite/build"),
        emptyOutDir: false,
        sourcemap: true,
        rollupOptions: {
          input: { preload: path.resolve(__dirname, "src/main/preload.ts") },
          output: {
            format: "cjs",
            inlineDynamicImports: true,
            entryFileNames: "preload.js",
            chunkFileNames: "[name].js",
            assetFileNames: "[name].[ext]",
          },
          external: [
            "electron",
            "electron/renderer",
            "electron/common",
            ...nodeExternals,
          ],
        },
      },
    },

    renderer: {
      root: __dirname,
      plugins: [
        // Dev-only "Go to Source" helper: AST transform that stamps every JSX
        // element with data-tsd-source="<file>:<line>:<col>". Hold the inspector
        // hotkey (Shift+Alt+Ctrl/Meta) to reveal an element's source location.
        // Must be first so it sees JSX before other transforms.
        isDev &&
          tanstackDevtools({
            injectSource: { enabled: true },
          }),
        TanStackRouterVite({
          target: "react",
          autoCodeSplitting: true,
          routesDirectory: path.resolve(
            __dirname,
            "../../packages/ui/src/router/routes",
          ),
          generatedRouteTree: path.resolve(
            __dirname,
            "../../packages/ui/src/router/routeTree.gen.ts",
          ),
        }),
        tailwindcss(),
        react(),
        tsconfigPaths({ ignoreConfigErrors: true }),
        createPosthogPlugin(env, "posthog-code-renderer"),
      ].filter(Boolean),
      worker: {
        format: "es",
      },
      envDir: path.resolve(__dirname, "../.."),
      define: {
        ...createForceDevModeDefine(),
        __APP_VERSION__: JSON.stringify(pkg.version),
      },
      resolve: {
        alias: rendererAliases,
        dedupe: ["react", "react-dom"],
      },
      server: {
        port: 5173,
      },
      build: {
        outDir: path.join(__dirname, ".vite/renderer/main_window"),
        sourcemap: true,
        rollupOptions: {
          input: path.resolve(__dirname, "index.html"),
        },
      },
    },
  };
});
