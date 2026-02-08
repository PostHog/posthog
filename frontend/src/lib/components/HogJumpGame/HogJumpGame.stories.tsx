import { Meta, StoryFn } from '@storybook/react'

import { HogJumpError, HogJumpErrorProps } from './HogJumpError'
import { HogJumpGame, HogJumpGameProps } from './HogJumpGame'

const meta: Meta<typeof HogJumpGame> = {
    title: 'Components/HogJumpGame',
    component: HogJumpGame,
    parameters: {
        layout: 'centered',
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof HogJumpGame> = (args: HogJumpGameProps) => {
    return <HogJumpGame {...args} />
}

export const Default = Template.bind({})
Default.args = {
    isActive: true,
}

export const AsErrorComponent = Template.bind({})
AsErrorComponent.args = {
    isActive: true,
    title: 'Oops! Something went wrong',
    subtitle: 'While we fix this, why not play a game?',
}

export const NoTitle = Template.bind({})
NoTitle.args = {
    isActive: true,
    title: undefined,
    subtitle: undefined,
}

const ErrorTemplate: StoryFn<typeof HogJumpError> = (args: HogJumpErrorProps) => {
    return <HogJumpError {...args} />
}

export const ErrorBoundaryFallback = ErrorTemplate.bind({})
ErrorBoundaryFallback.args = {
    error: new Error('Cannot read property "foo" of undefined'),
    exceptionId: 'abc-123-def-456',
}

export const ErrorBoundaryFallbackMinimal = ErrorTemplate.bind({})
ErrorBoundaryFallbackMinimal.args = {}
