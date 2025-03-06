import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { ProfilePicture } from '../ProfilePicture'
import { LemonSnack, LemonSnackProps } from './LemonSnack'

type Story = StoryObj<typeof LemonSnack>
const meta: Meta<typeof LemonSnack> = {
    title: 'Lemon UI/Lemon Snack',
    component: LemonSnack,
    args: {
        children: 'Tasty snacks',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof LemonSnack> = (props: LemonSnackProps) => {
    return <LemonSnack {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {
    onClose: null as any,
}

export const Pill = (): JSX.Element => {
    return (
        <div className="flex flex-row deprecated-space-x-2">
            <LemonSnack type="pill">Pill</LemonSnack>
            <LemonSnack type="pill" onClick={() => alert('onClick')}>
                Clickable
            </LemonSnack>
            <LemonSnack type="pill" onClose={() => alert('onClose')}>
                Closeable
            </LemonSnack>
            <LemonSnack type="pill" onClick={() => alert('onClick')} onClose={() => alert('onClose')}>
                Click- and Closeable
            </LemonSnack>
        </div>
    )
}

export const ComplexContent: Story = BasicTemplate.bind({})
ComplexContent.args = {
    children: (
        <span className="flex gap-2 items-center">
            <ProfilePicture name="ben" size="sm" />
            <span>
                Look at me I'm <b>bold!</b>
            </span>
        </span>
    ),
    onClose: () => alert('Close clicked!'),
}

export const OverflowOptions = (): JSX.Element => {
    return (
        <>
            <p>By default the LemonSnack does not wrap content but this can be changed with the wrap property</p>
            <div className="bg-border p-2 deprecated-space-y-2 w-60">
                <LemonSnack onClose={() => {}}>qwertzuiopasdfghjklyxcvbnm1234567890</LemonSnack>
                <LemonSnack onClose={() => {}} wrap>
                    Overflow-qwertzuiopasdfghjklyxcvbnm1234567890
                </LemonSnack>
            </div>
        </>
    )
}
