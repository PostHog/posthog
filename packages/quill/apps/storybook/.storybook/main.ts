import type { StorybookConfig } from '@storybook/react-vite'
import path from 'path'

const config: StorybookConfig = {
    stories: [
        '../stories/**/*.mdx',
        '../stories/**/*.stories.@(js|jsx|mjs|ts|tsx)',
        // Also pick up stories co-located in packages
        '../../../packages/*/src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
    ],
    addons: ['storybook-addon-pseudo-states'],
    framework: {
        name: '@storybook/react-vite',
        options: {},
    },
    viteFinal: async (config) => {
        const { default: tailwindcss } = await import('@tailwindcss/vite')

        config.plugins = [...(config.plugins || []), tailwindcss()]
        config.resolve = {
            ...config.resolve,
            alias: {
                ...config.resolve?.alias,
                // Points to primitives/src so @/ imports in primitive components resolve
                '@': path.resolve(__dirname, '../../../packages/primitives/src'),
            },
        }

        return config
    },
}

export default config
