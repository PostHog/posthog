import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { ClampedText, ClampedTextProps } from './ClampedText'

type Story = StoryObj<typeof ClampedText>
const meta: Meta<typeof ClampedText> = {
    title: 'Lemon UI/ClampedText',
    component: ClampedText,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof ClampedText> = (props: ClampedTextProps) => {
    return <ClampedText {...props} />
}

export const SingleLine: Story = Template.bind({})
SingleLine.args = { lines: 2, text: 'One line of text' }

export const MultiLine: Story = Template.bind({})
MultiLine.args = {
    lines: 2,
    text: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.',
}
