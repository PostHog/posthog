import { Decorator } from '@storybook/react'
import { inStorybookTestRunner } from 'lib/utils'

/** Workaround for https://github.com/storybookjs/test-runner/issues/74 */
// TODO: Smoke-test all the stories by removing this decorator, once all the stories pass
export const withSnapshotsDisabled: Decorator = (Story, { parameters }) => {
    if (parameters?.testOptions?.skip && inStorybookTestRunner()) {
        return <>Disabled for Test Runner</>
    }
    return <Story />
}
