import { StorybookConfig } from 'storybook-react-rsbuild'

const config: StorybookConfig = {
    framework: 'storybook-react-rsbuild',
    rsbuildFinal: (config) => {
        // Customize the final Rsbuild config here
        return config
    },

    stories: ['../frontend/src/**/*.mdx', '../frontend/src/**/*.stories.@(js|jsx|ts|tsx)'],
    addons: [
        '@storybook/addon-docs',
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
        'storybook-addon-pseudo-states',
    ],

    staticDirs: ['public', { from: '../frontend/public', to: '/static' }],
}

export default config
