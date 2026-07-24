import { defineConfig } from 'tsup'

// Dual ESM/CJS build + type declarations. The generated resource layer and the
// vendored `Schemas` namespace are pulled in through `src/index.ts`; runtime Zod
// never reaches the bundle (input types are plain TS materialized at generate
// time), which `test` asserts by grepping the dist output.
export default defineConfig({
    entry: ['src/index.ts'],
    format: ['esm', 'cjs'],
    dts: true,
    sourcemap: true,
    clean: true,
    treeshake: true,
    target: 'es2021',
    outExtension({ format }) {
        return { js: format === 'cjs' ? '.cjs' : '.js' }
    },
})
