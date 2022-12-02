import type { DecoratorFn } from '@storybook/react'
import MockDate from 'mockdate'

export const withMockDate: DecoratorFn = (Story, { parameters }) => {
    MockDate.reset()

    if (!parameters.mockdate) {
        return <Story />
    }

    MockDate.set(parameters.mockdate)
    return <Story />
}
