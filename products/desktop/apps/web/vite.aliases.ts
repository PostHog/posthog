import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));
const src = (name: string) => path.resolve(dir, `../../packages/${name}/src`);

// Mirror apps/code's vite.shared.mts: resolve @posthog/<pkg>/<sub> to package
// src, since the packages' array-fallback `exports` don't resolve under Rollup.
// Shared by vite.config.ts (build/dev) and vitest.config.ts (tests) so the two
// can't drift.
const subpath = (name: string) => ({
  find: new RegExp(`^@posthog/${name}/(.+)$`),
  replacement: `${src(name)}/$1`,
});

export const posthogSrcAliases = [
  subpath("di"),
  subpath("ui"),
  subpath("core"),
  subpath("shared"),
  subpath("host-router"),
  subpath("host-trpc"),
  subpath("platform"),
  subpath("workspace-client"),
  subpath("api-client"),
  subpath("agent"),
  subpath("enricher"),
  subpath("git"),
];
