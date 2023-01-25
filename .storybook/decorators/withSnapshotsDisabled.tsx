import { DecoratorFn } from '@storybook/react'

/** Workaround for https://github.com/storybookjs/test-runner/issues/74 */
// TODO: Smoke-test all the stories by removing this decorator, once all the stories pass
export const withSnapshotsDisabled: DecoratorFn = (Story, { parameters }) => {
    if (parameters?.chromatic?.disableSnapshot !== false && navigator.userAgent.includes('StorybookTestRunner')) {
        return <>Disabled for Test Runner</>
    }
    return <Story />
}
