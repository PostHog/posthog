import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonButton, LemonButtonProps } from './LemonButton'
import { IconCalculate } from 'lib/lemon-ui/icons'
import { FEATURE_FLAGS } from 'lib/constants'

type Story = StoryObj<typeof LemonButton>
const meta: Meta<typeof LemonButton> = {
    title: 'Lemon UI/Lemon Button 3000',
    component: LemonButton,
    tags: ['autodocs'],
    argTypes: {
        icon: {
            type: 'function',
        },
    },
}
export default meta
const BasicTemplate: StoryFn<typeof LemonButton> = (props: LemonButtonProps) => {
    return <LemonButton {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {
    icon: <IconCalculate />,
    children: 'Click me',
}

export const Hover: Story = {
    play: async (props) => {
        debugger
    },
}

// export const Hover: Story = () => {
//     return <LemonButton type="primary">Click me</LemonButton>
// }
// Hover.parameters = { pseudo: { hover: true }, featureFlags: [FEATURE_FLAGS.POSTHOG_3000] }

export const Active = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <p>
                Sometimes you may need to keep the LemonButton in it's active state e.g. the hover state. This can be
                done by setting the <code>active</code> property
            </p>
            <div className="flex items-center gap-2">
                <LemonButton>I am not active</LemonButton>
                <LemonButton active>I am active</LemonButton>
            </div>
        </div>
    )
}
