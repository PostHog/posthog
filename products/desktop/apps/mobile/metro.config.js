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

// Force React to resolve from monorepo root, and alias workspace packages
// directly to their TypeScript source so Babel can transpile them (Metro
// does not consume the ESM `dist/` build cleanly).
config.resolver.extraNodeModules = {
  react: path.resolve(monorepoRoot, "node_modules/react"),
  "@posthog/shared": path.resolve(monorepoRoot, "packages/shared/src/index.ts"),
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

module.exports = nativeWindConfig;
