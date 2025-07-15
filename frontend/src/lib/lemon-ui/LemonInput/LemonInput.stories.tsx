import { IconCalendar, IconChevronDown } from '@posthog/icons'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { userEvent } from '@storybook/testing-library'
import { LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { useState } from 'react'

import { LemonInput } from './LemonInput'

type Story = StoryObj<typeof LemonInput>
const meta: Meta<typeof LemonInput> = {
    title: 'Lemon UI/Lemon Input',
    component: LemonInput,
    tags: ['autodocs'],
    args: {
        value: 'Foo',
    },
}
export default meta

const Template: StoryFn<typeof LemonInput> = (props) => {
    const [value, setValue] = useState(props.value)
    // @ts-expect-error – union variant inference around the `type` prop doesn't work here as `type` comes from above
    return <LemonInput {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Basic: Story = Template.bind({})

export const WithPrefixAndSuffixAction: Story = Template.bind({})
WithPrefixAndSuffixAction.args = {
    prefix: <IconCalendar />,
    suffix: (
        <LemonButtonWithDropdown
            noPadding
            dropdown={{
                overlay: 'Surprise! 😱',
            }}
            type="tertiary"
            icon={<IconChevronDown />}
        />
    ),
}

export const DisabledWithReason: Story = Template.bind({})
DisabledWithReason.args = { disabledReason: "You're not cool enough to click this." }
DisabledWithReason.play = async ({ canvasElement }: { canvasElement: HTMLElement }) => {
    const inputWrapper = canvasElement.querySelector('.LemonInput')
    if (inputWrapper) {
        await userEvent.hover(inputWrapper)
        await new Promise((resolve) => setTimeout(resolve, 100))
    }
}

export const Search: Story = Template.bind({})
Search.args = { type: 'search', placeholder: 'Search your soul' }

export const Password: Story = Template.bind({})
Password.args = { type: 'password', placeholder: 'Enter your password' }

export const Disabled: Story = Template.bind({})
Disabled.args = { disabled: true }

export const DangerStatus: Story = Template.bind({})
DangerStatus.args = { status: 'danger' }

export const Clearable: Story = Template.bind({})
Clearable.args = { allowClear: true }

export const Numeric: Story = Template.bind({})
Numeric.args = { type: 'number', min: 0, step: 1, value: 3 }

export const Small: Story = Template.bind({})
Small.args = { allowClear: true, size: 'small' }

export const Prefix: Story = Template.bind({})
Prefix.args = { allowClear: true, size: 'small', prefix: <IconCalendar /> }
