// The tool catalog bundle `pnpm --filter @posthog/mcp build:cli:library` writes. Its contract lives
// in a file with no imports, so hog type-checks without compiling the MCP sources.
declare module '@posthog/mcp/dist/cli-library.mjs' {
    export function createApiToolLibrary(): import('@posthog/mcp/src/cli/library-types').ApiToolLibrary
}
