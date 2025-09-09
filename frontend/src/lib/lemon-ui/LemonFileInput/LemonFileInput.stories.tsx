import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { createRef, useState } from 'react'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'

type Story = StoryObj<typeof LemonFileInput>
const meta: Meta<typeof LemonFileInput> = {
    title: 'Lemon UI/Lemon File Input',
    component: LemonFileInput,
    tags: ['autodocs'],
    argTypes: {
        loading: { type: 'boolean' },
        accept: { type: 'string' },
    },
    args: {
        loading: false,
        accept: '.json',
    },
}
export default meta

const Template: StoryFn<typeof LemonFileInput> = (props) => {
    const [singleValue, setSingleValue] = useState([] as any[])

    return (
        <div className="flex flex-col gap-4">
            <LemonFileInput
                loading={props.loading}
                {...props}
                value={singleValue}
                onChange={(newValue) => setSingleValue(newValue)}
            />
        </div>
    )
}

export const SingleUploadAccepted: Story = Template.bind({})

export const MultiUploadAccepted: Story = Template.bind({})
MultiUploadAccepted.args = {
    multiple: true,
}

export const SpecificType: Story = Template.bind({})
SpecificType.args = {
    accept: 'image/*',
}

export const CustomCTA: Story = Template.bind({})
CustomCTA.args = {
    callToAction: <div>i am a custom CTA, i could be any valid element</div>,
}

export const ExtraDragAndDropTarget: StoryFn<typeof LemonFileInput> = (props) => {
    const [extraTargetValue, setExtraTargetValue] = useState([] as any[])

    const additionalDragTarget = createRef<HTMLDivElement>()

    return (
        <div className="flex flex-col gap-4">
            <div ref={additionalDragTarget} className="h-12 w-full border flex items-center justify-center">
                This area is also a drag target
            </div>
            <LemonFileInput
                {...props}
                value={extraTargetValue}
                onChange={(newValue) => setExtraTargetValue(newValue)}
                alternativeDropTargetRef={additionalDragTarget}
            />
        </div>
    )
}
