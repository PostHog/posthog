const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");
const path = require("node:path");

const projectRoot = __dirname;
const monorepoRoot = path.resolve(projectRoot, "../..");

const config = getDefaultConfig(projectRoot);

// Watch monorepo root for changes
config.watchFolders = [monorepoRoot];

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

// Resolve @posthog/shared to its TypeScript source so Babel transpiles it.
// Its package.json `exports` point at `dist/`, which is only present after a
// `pnpm build` -- EAS Build never runs one, so bundling there fails outright.
// This must be a resolveRequest hook rather than an `extraNodeModules` alias:
// pnpm symlinks the package into node_modules, so Metro resolves it there
// first and never consults the alias, and an alias also cannot map subpath
// imports like `@posthog/shared/domain-types`.
const SHARED_PACKAGE = "@posthog/shared";
const sharedSrc = path.resolve(monorepoRoot, "packages/shared/src");
const upstreamResolveRequest = nativeWindConfig.resolver.resolveRequest;

nativeWindConfig.resolver.resolveRequest = (context, moduleName, platform) => {
  if (
    moduleName === SHARED_PACKAGE ||
    moduleName.startsWith(`${SHARED_PACKAGE}/`)
  ) {
    const subpath = moduleName.slice(SHARED_PACKAGE.length + 1) || "index";
    return context.resolveRequest(
      context,
      path.join(sharedSrc, subpath),
      platform,
    );
  }

  return (upstreamResolveRequest ?? context.resolveRequest)(
    context,
    moduleName,
    platform,
  );
};

module.exports = nativeWindConfig;
