import { StorybookConfig } from '@storybook/react-vite'

const config: StorybookConfig = {
    stories: ['../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)'],
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

    typescript: { reactDocgen: 'react-docgen' }, // Shouldn't be needed in Storybook 8
}

export default config
