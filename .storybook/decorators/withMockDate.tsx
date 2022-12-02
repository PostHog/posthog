import type { DecoratorFn } from '@storybook/react'
import MockDate from 'mockdate'

export const withMockDate: DecoratorFn = (Story, { parameters }) => {
    if (parameters.mockDate) {
        MockDate.set(parameters.mockDate)
    } else {
        MockDate.reset()
    }

    return <Story />
}
