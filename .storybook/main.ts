import { StorybookConfig } from '@storybook/react-vite'

const config: StorybookConfig = {
    stories: ['../frontend/src/**/*.mdx', '../frontend/src/**/*.stories.@(js|jsx|ts|tsx)'],
    framework: '@storybook/react-vite',

    addons: [
        '@storybook/addon-docs',
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
        'storybook-addon-pseudo-states',
    ],

    staticDirs: ['public', { from: '../frontend/public', to: '/static' }],

    docs: {},

}

export default config
