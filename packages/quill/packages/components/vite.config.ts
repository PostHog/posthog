import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

export default defineConfig({
    plugins: [react(), tailwindcss(), dts({ tsconfigPath: resolve(__dirname, 'tsconfig.build.json') })],
    build: {
        lib: {
            // `metric` is a separate entry (not part of the main barrel) so its `@posthog/quill-charts`
            // dependency only loads for consumers that import `@posthog/quill-components/metric`.
            entry: {
                index: resolve(__dirname, 'src/index.ts'),
                metric: resolve(__dirname, 'src/metric.tsx'),
            },
            formats: ['es', 'cjs'],
            fileName: (format, entryName) => `${entryName}.${format === 'es' ? 'js' : 'cjs'}`,
        },
        rollupOptions: {
            // One ES file per source module. See the primitives config for the reason.
            output: [
                { format: 'es', preserveModules: true, preserveModulesRoot: 'src', entryFileNames: '[name].js' },
                { format: 'cjs', entryFileNames: '[name].cjs' },
            ],
            external: [
                'react',
                'react-dom',
                'react/jsx-runtime',
                '@posthog/quill-tokens',
                '@posthog/quill-primitives',
                '@posthog/quill-charts',
            ],
        },
        cssCodeSplit: false,
    },
})
