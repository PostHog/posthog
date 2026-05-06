// `@tailwindcss/vite` only declares types via `package.json#exports`, which the
// project's `moduleResolution: "node"` setting does not read. This shim lets
// `tsc --noEmit` resolve the plugin without changing the project-wide module
// resolution strategy.
declare module '@tailwindcss/vite' {
    import type { Plugin } from 'vite'
    const tailwindcss: () => Plugin[]
    export default tailwindcss
}
