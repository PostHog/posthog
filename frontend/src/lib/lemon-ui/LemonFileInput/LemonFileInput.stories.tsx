import type { Meta, StoryObj } from '@storybook/react'
import { createRef, useState } from 'react'

import { LemonFileInput, LemonFileInputProps } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'

type Story = StoryObj<LemonFileInputProps>
const meta: Meta<LemonFileInputProps> = {
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
    render: (props) => {
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
    },
}
export default meta

export const SingleUploadAccepted: Story = {}

export const MultiUploadAccepted: Story = {
    args: {
        multiple: true,
    },
}

export const SpecificType: Story = {
    args: {
        accept: 'image/*',
    },
}

export const CustomCTA: Story = {
    args: {
        callToAction: <div>i am a custom CTA, i could be any valid element</div>,
    },
}

export const ExtraDragAndDropTarget: Story = {
    render: (props) => {
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
    },
}
