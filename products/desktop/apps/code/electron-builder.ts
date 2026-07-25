import { createRequire } from "node:module";
import type { Configuration } from "electron-builder";
import { asarUnpackGlobs, packagedFileGlobs } from "./runtime-dependencies";
import beforePack from "./scripts/before-pack";

const require = createRequire(import.meta.url);

const skipNotarize =
  process.env.SKIP_NOTARIZE === "1" || !process.env.APPLE_TEAM_ID;

// --- Windows code signing (security: signed Windows auto-updates) -----------
// Unsigned Windows installers make electron-updater skip Authenticode
// verification of downloaded updates: the only integrity check left is the
// SHA512 in latest.yml, served from the SAME feed, so a compromised feed/CDN or
// a TLS-MITM can serve a malicious installer that the app runs on next quit.
// Signing the installer and pinning `publisherName` makes electron-updater
// verify each downloaded installer's Authenticode signature before applying it
// (`win.verifyUpdateCodeSignature` defaults to true and checks publisherName).
//
// REQUIRED SECRETS (wired in .github/workflows/code-release.yml; see PR):
//   WINDOWS_PUBLISHER_NAME  - subject CN of the signing certificate, e.g.
//                             "PostHog, Inc." MUST match the certificate
//                             exactly; it is written into app-update.yml and
//                             checked by electron-updater on every update.
//   Preferred - Azure Trusted Signing (no .pfx to manage on the runner;
//   electron-builder auto-installs the TrustedSigning PowerShell module):
//     AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET  (Entra ID auth)
//     AZURE_CODE_SIGNING_ENDPOINT   - e.g. https://eus.codesigning.azure.net/
//     AZURE_CODE_SIGNING_ACCOUNT    - Trusted Signing account name
//     AZURE_CERT_PROFILE_NAME       - certificate profile name
//   Fallback - PFX certificate via electron-builder's standard env vars:
//     WIN_CSC_LINK / WIN_CSC_KEY_PASSWORD
//
// Local/dev builds without these secrets (or SKIP_WINDOWS_SIGN=1) stay unsigned,
// mirroring how SKIP_NOTARIZE gates macOS notarization above.
const windowsPublisherName = process.env.WINDOWS_PUBLISHER_NAME;
const azureEndpoint = process.env.AZURE_CODE_SIGNING_ENDPOINT;
const azureAccount = process.env.AZURE_CODE_SIGNING_ACCOUNT;
const azureCertProfile = process.env.AZURE_CERT_PROFILE_NAME;

function windowsSigningOptions(): Pick<
  NonNullable<Configuration["win"]>,
  "azureSignOptions" | "signtoolOptions"
> {
  // No publisher name -> nothing for electron-updater to verify against, so
  // leave the build unsigned (dev/local); CI always supplies the secrets.
  if (process.env.SKIP_WINDOWS_SIGN === "1" || !windowsPublisherName) {
    return {};
  }
  // Preferred: Azure Trusted Signing.
  if (azureEndpoint && azureAccount && azureCertProfile) {
    return {
      azureSignOptions: {
        publisherName: windowsPublisherName,
        endpoint: azureEndpoint,
        codeSigningAccountName: azureAccount,
        certificateProfileName: azureCertProfile,
      },
    };
  }
  // Fallback: signtool reads the .pfx from WIN_CSC_LINK / WIN_CSC_KEY_PASSWORD.
  if (process.env.WIN_CSC_LINK) {
    return {
      signtoolOptions: {
        publisherName: windowsPublisherName,
        signingHashAlgorithms: ["sha256"],
      },
    };
  }
  return {};
}

const config: Configuration = {
  // Original release bundle id; changing it breaks existing installs' data dir and Keychain entries.
  appId: "com.posthog.array",
  productName: "PostHog",
  executableName: "PostHog",

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
    ".vite/build/rpc-host.js",
    ".vite/build/rpc-host.js.map",
    ...asarUnpackGlobs,
  ],

  extraResources: [
    { from: "build/app-icon.png", to: "app-icon.png" },
    { from: "build/Assets.car", to: "Assets.car" },
  ],

  protocols: [
    {
      name: "PostHog",
      schemes: ["posthog-code"],
    },
  ],

  mac: {
    target: ["dmg", "zip"],
    // biome-ignore lint/suspicious/noTemplateCurlyInString: electron-builder interpolation tokens, not JS template literals
    artifactName: "PostHog-Code-${version}-${arch}-mac.${ext}",
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
    // biome-ignore lint/suspicious/noTemplateCurlyInString: electron-builder interpolation tokens, not JS template literals
    artifactName: "PostHog-Code-${version}-${arch}-win.${ext}",
    // electron-builder generates the multi-size .ico from this 1024px PNG; a real
    // .ico must be >=256px and the committed app-icon.ico is only 32px.
    icon: "build/app-icon.png",
    // Verify a downloaded update's Authenticode signature (against publisherName)
    // before installing it. Default is true; set explicitly because it is the
    // check that closes the unsigned-auto-update RCE. See the signing note above.
    verifyUpdateCodeSignature: true,
    ...windowsSigningOptions(),
  },

  nsis: {
    oneClick: false,
    deleteAppDataOnUninstall: false,
  },

  linux: {
    target: ["AppImage", "deb", "rpm"],
    // biome-ignore lint/suspicious/noTemplateCurlyInString: electron-builder interpolation tokens, not JS template literals
    artifactName: "PostHog-Code-${version}-${arch}-linux.${ext}",
    icon: "build/app-icon.png",
    category: "Development",
    mimeTypes: ["x-scheme-handler/posthog-code"],
  },

  deb: {
    packageName: "posthog-code",
    maintainer: "PostHog <eng@posthog.com>",
    packageCategory: "devel",
  },

  rpm: {
    packageName: "posthog-code",
  },

  // Installs built from this config poll the CloudFront-fronted update feed
  // (the S3 bucket is private; reads go through the CDN). Installs built before
  // the feed moved poll GitHub Releases on PostHog/code, so CI dual-publishes
  // there until that fleet drains.
  publish: {
    provider: "generic",
    url: "https://desktop-releases.posthog.com/stable",
  },
};

export default config;
