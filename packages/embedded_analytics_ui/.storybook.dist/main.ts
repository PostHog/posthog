import mainConfig from '../.storybook/main'

const config = {
    ...mainConfig,
    stories: ['../tests/**/*.stories.@(js|jsx|mjs|ts|tsx)'],
}

export default config
