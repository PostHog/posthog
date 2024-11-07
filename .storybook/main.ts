import { StorybookConfig } from 'storybook-react-rsbuild'

const config: StorybookConfig = {
    framework: 'storybook-react-rsbuild',

    stories: ['../frontend/src/**/*.mdx', '../frontend/src/**/*.stories.@(js|jsx|ts|tsx)'],
    addons: [
        // '@storybook/addon-docs',
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
        'storybook-addon-pseudo-states',
    ],

    staticDirs: ['public', { from: '../frontend/public', to: '/static' }],
    docs: {
        docsMode: false,
    },
    typescript: {
        reactDocgen: false,
    },
}

export default config
