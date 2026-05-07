import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

export default defineConfig({
    plugins: [
        react(),
        tailwindcss(),
        dts({
            tsconfigPath: resolve(__dirname, 'tsconfig.build.json'),
            exclude: ['src/**/*.stories.tsx', 'src/**/*.stories.ts'],
        }),
    ],
    build: {
        lib: {
            entry: resolve(__dirname, 'src/index.ts'),
            formats: ['es', 'cjs'],
            fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
        },
        rollupOptions: {
            external: [
                'react',
                'react-dom',
                'react/jsx-runtime',
                '@posthog/quill-tokens',
                '@base-ui/react',
                /^@base-ui\/react\//,
                'lucide-react',
                'vaul',
                'react-resizable-panels',
                'class-variance-authority',
                'clsx',
                'tailwind-merge',
                'tw-animate-css',
                '@fontsource-variable/inter',
            ],
        },
        cssCodeSplit: false,
    },
})
