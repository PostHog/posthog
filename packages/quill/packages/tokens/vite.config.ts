import { resolve } from 'path'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

export default defineConfig({
    plugins: [
        dts({
            exclude: ['src/build.ts'],
            tsconfigPath: resolve(__dirname, 'tsconfig.build.json'),
        }),
    ],
    build: {
        lib: {
            entry: resolve(__dirname, 'src/index.ts'),
            formats: ['es', 'cjs'],
            fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
        },
        outDir: 'dist',
        emptyOutDir: false, // Preserve generated CSS files
    },
})
