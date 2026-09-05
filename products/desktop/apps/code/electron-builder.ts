import { createRequire } from "node:module";
import type { Configuration } from "electron-builder";
import { asarUnpackGlobs, packagedFileGlobs } from "./runtime-dependencies";
import beforePack from "./scripts/before-pack";
import {
  assertOrdinaryBuild,
  loadPreviewBuildConfig,
} from "./scripts/preview-config.mts";

const require = createRequire(import.meta.url);

const skipNotarize =
  process.env.SKIP_NOTARIZE === "1" || !process.env.APPLE_TEAM_ID;

// Preview packaging: one identity per PR, no updater feed. An ordinary build
// fails closed when preview configuration is present.
const preview = loadPreviewBuildConfig();
if (!preview) {
  assertOrdinaryBuild(null);
}

const config: Configuration = {
  // Original release bundle id; changing it breaks existing installs' data dir and Keychain entries.
  appId: preview ? preview.identity.appId : "com.posthog.array",
  productName: preview ? preview.identity.productName : "PostHog",
  executableName: preview ? preview.identity.executableName : "PostHog",

  directories: {
    output: "out",
    buildResources: "build",
  },

  electronVersion: require("electron/package.json").version,
  npmRebuild: false,
  nodeGypRebuild: false,
  generateUpdatesFilesForAllChannels: true,

  // English-only product: drop the ~50 other Electron locales (~50 MB).
  electronLanguages: ["en", "en-US"],

  beforePack,

  files: [
    ".vite/build/**/*",
    ".vite/renderer/**/*",
    "package.json",
    "!node_modules/**/*",
    ...packagedFileGlobs,
    // Sourcemaps are uploaded to PostHog at build time, not consumed in the app.
    "!**/*.map",
    // better-sqlite3 ships its C amalgamation sources; only the built .node runs.
    "!node_modules/better-sqlite3/deps/**",
    "!node_modules/better-sqlite3/src/**",
  ],

  asarUnpack: [
    "**/*.node",
    "**/spawn-helper",
    ".vite/build/claude-cli/**",
    ".vite/build/plugins/posthog/**",
    ".vite/build/codex-acp/**",
    ".vite/build/grammars/**",
    ".vite/build/product-engineer/**",
    ".vite/build/rpc-host.js",
    ".vite/build/rpc-host.js.map",
    ".vite/build/adapters/codex-app-server/local-tools-mcp-server.js",
    ...asarUnpackGlobs,
  ],

  extraResources: [
    { from: "build/app-icon.png", to: "app-icon.png" },
    { from: "build/Assets.car", to: "Assets.car" },
  ],

  protocols: [
    {
      name: preview ? preview.identity.productName : "PostHog",
      schemes: preview ? [preview.identity.scheme] : ["posthog-code"],
    },
  ],

  mac: {
    target: ["dmg", "zip"],
    artifactName: preview
      ? `${preview.identity.artifactPrefix}-\${version}-\${arch}-mac.\${ext}`
      : // biome-ignore lint/suspicious/noTemplateCurlyInString: electron-builder interpolation tokens, not JS template literals
        "PostHog-Desktop-${version}-${arch}-mac.${ext}",
    icon: "build/app-icon.icns",
    category: "public.app-category.productivity",
    hardenedRuntime: true,
    gatekeeperAssess: false,
    entitlements: "build/entitlements.mac.plist",
    entitlementsInherit: "build/entitlements.mac.inherit.plist",
    extendInfo: {
      CFBundleIconName: "Icon",
      // Shown in the macOS microphone-permission prompt when a user records a
      // custom notification sound.
      NSMicrophoneUsageDescription:
        "PostHog uses the microphone to record custom notification sounds.",
    },
    notarize: !skipNotarize,
  },

  dmg: {
    format: "ULFO",
    size: "4g",
    background: "build/dmg-background.png",
    icon: "build/app-icon.icns",
    iconSize: 80,
    window: { width: 560, height: 380 },
    contents: [
      { x: 104, y: 55, type: "file" },
      { x: 104, y: 243, type: "link", path: "/Applications" },
    ],
  },

  win: {
    target: ["nsis"],
    artifactName: preview
      ? `${preview.identity.artifactPrefix}-\${version}-\${arch}-win.\${ext}`
      : // biome-ignore lint/suspicious/noTemplateCurlyInString: electron-builder interpolation tokens, not JS template literals
        "PostHog-Desktop-${version}-${arch}-win.${ext}",
    // electron-builder generates the multi-size .ico from this 1024px PNG; a real
    // .ico must be >=256px and the committed app-icon.ico is only 32px.
    icon: "build/app-icon.png",
  },

  nsis: {
    oneClick: false,
    deleteAppDataOnUninstall: false,
  },

  linux: {
    target: ["AppImage", "deb", "rpm"],
    artifactName: preview
      ? `${preview.identity.artifactPrefix}-\${version}-\${arch}-linux.\${ext}`
      : // biome-ignore lint/suspicious/noTemplateCurlyInString: electron-builder interpolation tokens, not JS template literals
        "PostHog-Desktop-${version}-${arch}-linux.${ext}",
    icon: "build/app-icon.png",
    category: "Development",
    mimeTypes: preview
      ? [`x-scheme-handler/${preview.identity.scheme}`]
      : ["x-scheme-handler/posthog-code"],
  },

  deb: {
    packageName: preview ? preview.identity.userDataDirName : "posthog-code",
    maintainer: "PostHog <eng@posthog.com>",
    packageCategory: "devel",
  },

  rpm: {
    packageName: preview ? preview.identity.userDataDirName : "posthog-code",
  },

  // Installs built from this config poll the CloudFront-fronted update feed
  // (the S3 bucket is private; reads go through the CDN). A preview build
  // publishes no feed metadata at all: there is nothing to update to, and the
  // updater is disabled in preview builds (electron-updater.ts) so neither the
  // poll nor a manual "check for updates" can reach the stable feed.
  ...(preview
    ? {}
    : {
        publish: {
          provider: "generic",
          url: "https://desktop-releases.posthog.com/stable",
        },
      }),
};

export default config;
