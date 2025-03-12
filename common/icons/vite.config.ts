import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import * as pkg from './package.json'
import dts from 'vite-plugin-dts'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react(), dts()],
    build: {
        minify: false,
        sourcemap: true,
        emptyOutDir: false,
        lib: {
            entry: './src/index.ts',
            name: 'PostHogIcons',
            formats: ['es', 'cjs'],
            fileName: (format) => `posthog-icons.${format}.js`,
        },
        rollupOptions: {
            external: [...Object.keys(pkg.peerDependencies)],
        },
    },
})
