const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");
const path = require("node:path");

const projectRoot = __dirname;
const monorepoRoot = path.resolve(projectRoot, "../..");
const agentContractsRoot = path.resolve(
  monorepoRoot,
  "../../packages/agent/packages/agent-contracts",
);

const config = getDefaultConfig(projectRoot);

// Metro only bundles files under a watched folder, so agent-contracts is listed too.
config.watchFolders = [monorepoRoot, agentContractsRoot];

// Let Metro find modules in both locations
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(monorepoRoot, "node_modules"),
];

// Force React to resolve from monorepo root
config.resolver.extraNodeModules = {
  react: path.resolve(monorepoRoot, "node_modules/react"),
};

// Apply NativeWind first so its resolver/transformer changes are in place
// before we layer the SVG transformer on top.
const nativeWindConfig = withNativeWind(config, { input: "./global.css" });

// Treat .svg files as React components via react-native-svg-transformer so
// we can `import Icon from "./logo.svg"` and render it like any RN component.
// This must run AFTER withNativeWind — NativeWind overwrites the resolver
// and would clobber the assetExts/sourceExts changes if applied later.
nativeWindConfig.transformer = {
  ...nativeWindConfig.transformer,
  babelTransformerPath: require.resolve("react-native-svg-transformer/expo"),
};
nativeWindConfig.resolver = {
  ...nativeWindConfig.resolver,
  assetExts: nativeWindConfig.resolver.assetExts.filter((ext) => ext !== "svg"),
  sourceExts: [...nativeWindConfig.resolver.sourceExts, "svg"],
};

// Resolve @posthog/shared, and the @posthog/agent-contracts package it
// re-exports, to their TypeScript source so Babel transpiles them.
// Their package.json `exports` point at `dist/`, which is only present after a
// `pnpm build` -- EAS Build never runs one, so bundling there fails outright.
// This must be a resolveRequest hook rather than an `extraNodeModules` alias:
// pnpm symlinks the package into node_modules, so Metro resolves it there
// first and never consults the alias, and an alias also cannot map subpath
// imports like `@posthog/shared/domain-types`.
const SOURCE_RESOLVED_PACKAGES = {
  "@posthog/shared": path.resolve(monorepoRoot, "packages/shared/src"),
  "@posthog/agent-contracts": path.resolve(agentContractsRoot, "src"),
};
const upstreamResolveRequest = nativeWindConfig.resolver.resolveRequest;

nativeWindConfig.resolver.resolveRequest = (context, moduleName, platform) => {
  for (const [packageName, src] of Object.entries(SOURCE_RESOLVED_PACKAGES)) {
    if (
      moduleName === packageName ||
      moduleName.startsWith(`${packageName}/`)
    ) {
      const subpath = moduleName.slice(packageName.length + 1) || "index";
      return context.resolveRequest(context, path.join(src, subpath), platform);
    }
  }

  return (upstreamResolveRequest ?? context.resolveRequest)(
    context,
    moduleName,
    platform,
  );
};

module.exports = nativeWindConfig;
