const { getDefaultConfig } = require("expo/metro-config");
const path = require("node:path");

const projectRoot = __dirname;
const monorepoRoot = path.resolve(projectRoot, "../..");

const config = getDefaultConfig(projectRoot);

config.watchFolders = [monorepoRoot];
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(monorepoRoot, "node_modules"),
];
config.resolver.extraNodeModules = {
  react: path.resolve(monorepoRoot, "node_modules/react"),
};

// @posthog/shared's package exports point at dist/, which only exists after a
// build. Resolve it to source so Babel transpiles it like the other packages.
const SHARED_PACKAGE = "@posthog/shared";
const sharedSrc = path.resolve(monorepoRoot, "packages/shared/src");
const upstreamResolveRequest = config.resolver.resolveRequest;

config.resolver.resolveRequest = (context, moduleName, platform) => {
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

module.exports = config;
