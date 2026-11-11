import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { HogQLEditor, HogQLEditorProps } from './HogQLEditor'

type Story = StoryObj<HogQLEditorProps>
const meta: Meta<HogQLEditorProps> = {
    title: 'Components/HogQLEditor',
    component: HogQLEditor,
    render: (props) => {
        const [value, onChange] = useState(props.value ?? "countIf(properties.$browser = 'Chrome')")
        // A fixed width: the snapshot root shrink-wraps its content, so Monaco would take whatever
        // width the root had at the moment it mounted.
        return (
            <div className="w-[32rem]">
                <HogQLEditor {...props} value={value} onChange={onChange} />
            </div>
        )
    },
    parameters: {
        // Every story renders Monaco unconditionally. Monaco loads through a lazy Suspense
        // facade, so without this the snapshot can be taken before or after it finishes
        // mounting, producing two different layouts for the same code. `.monaco-editor` also
        // matches Monaco's shared overflow root on <body>, so wait for the editor itself.
        testOptions: {
            waitForSelector: '.CodeEditor[data-editor-ready="true"]',
        },
    },
}
export default meta

export const HogQLEditor_: Story = {
    args: {},
}

export const NoValue: Story = {
    args: {
        value: '',
        disableAutoFocus: true,
    },
}

export const NoValuePersonPropertiesDisabled: Story = {
    args: {
        disablePersonProperties: true,
        value: '',
        disableAutoFocus: true,
    },
}
