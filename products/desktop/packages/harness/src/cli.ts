#!/usr/bin/env node

import {
  formatHogBrandBanner,
  installHogBrandEnv,
  isHelpRequest,
} from "./extensions/hog-branding/brand-env";
// Must run — and finish running — before `@earendil-works/pi-coding-agent`
// is evaluated, so pi picks up "hog" branding when its config module first
// evaluates. `installHogBrandEnv` itself only touches Node builtins, so
// this static import carries no ordering risk; everything below that
// touches pi-coding-agent (directly or transitively through the extension
// registry) is loaded dynamically instead of via a static import — see
// `./extensions/hog-branding/brand-env` for why a static
// import here wouldn't reliably run first once bundled, and why the extension
// registry below is imported by a *computed* (non-literal) specifier: a
// literal dynamic import is statically inlinable by a bundler. A specifier the
// bundler cannot resolve forces a genuine runtime load of the separately-built
// `dist/extensions/registry.js`.
import type * as ExtensionRegistry from "./extensions/registry";

installHogBrandEnv();

const { main, VERSION } = await import("@earendil-works/pi-coding-agent");
const extensionRegistryUrl = new URL(
  "./extensions/registry.js",
  import.meta.url,
).href;
const { harnessExtensionFiles }: typeof ExtensionRegistry = await import(
  extensionRegistryUrl
);

// pi generates its own `--help` text (see `cli/args.js`'s `printHelp()`)
// from `APP_NAME` alone, with no tagline — print ours first.
if (isHelpRequest(process.argv.slice(2))) {
  console.log(`${formatHogBrandBanner(VERSION)}\n`);
}

// Load every harness extension by file path (rather than via
// `extensionFactories`) so each shows its real name in the startup banner
// instead of `<inline:N>`; pi's loader only has a display name to show when
// an extension is loaded from a path.
const extensionArgs = harnessExtensionFiles().flatMap((file: string) => [
  "-e",
  file,
]);
main([...extensionArgs, ...process.argv.slice(2)]);
