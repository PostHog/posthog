import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonTag as LemonTagComponent, LemonTagType } from './LemonTag'

type Story = StoryObj<typeof LemonTagComponent>
const meta: Meta<typeof LemonTagComponent> = {
    title: 'Lemon UI/Lemon Tag',
    component: LemonTagComponent,
    tags: ['autodocs'],
    parameters: {
        testOptions: {
            include3000: true,
        },
    },
}
export default meta

const ALL_COLORS: LemonTagType[] = [
    'primary',
    'option',
    'highlight',
    'warning',
    'danger',
    'success',
    'default',
    'muted',
    'completion',
    'caution',
    'none',
]

const Template: StoryFn<typeof LemonTagComponent> = (props) => {
    return (
        <div className="flex gap-1 flex-wrap">
            {ALL_COLORS.map((type) => (
                <LemonTagComponent key={type} {...props} type={type}>
                    {type}
                </LemonTagComponent>
            ))}
        </div>
    )
}

export const LemonTag: Story = Template.bind({})
LemonTag.args = {}
