import { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { notebookDataframeHintLogic } from './notebookDataframeHintLogic'
import { NotebookDataframeHintPopover } from './NotebookDataframeHintPopover'

const SHORT_ID = '12345'
const NODE_ID = 'node-1'

// The SQL cell's footer, reduced to the input the hint anchors to, so the story shows the
// popover where a reader meets it rather than floating on its own.
function DataframeHintFooter(): JSX.Element {
    const [returnVariableInput, setReturnVariableInput] = useState<HTMLInputElement | null>(null)

    useEffect(() => {
        const logic = notebookDataframeHintLogic({ shortId: SHORT_ID })
        const unmount = logic.mount()
        logic.actions.showHint(NODE_ID)
        return unmount
    }, [])

    return (
        <div className="flex items-center gap-2 border-t border-primary bg-fill-highlight-50 p-2 text-xs text-muted">
            <input
                type="text"
                className="w-56 rounded border border-primary bg-surface-primary px-1.5 py-0.5 font-mono text-sm font-medium"
                placeholder="Output dataframe name"
                ref={setReturnVariableInput}
                readOnly
            />
            <NotebookDataframeHintPopover
                nodeId={NODE_ID}
                notebookShortId={SHORT_ID}
                referenceElement={returnVariableInput}
            />
        </div>
    )
}

const meta: Meta<typeof NotebookDataframeHintPopover> = {
    title: 'Scenes-App/Notebooks/Dataframe hint',
    component: NotebookDataframeHintPopover,
    parameters: {
        featureFlags: [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS],
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof NotebookDataframeHintPopover>

export const OnACellWithNoDataframeName: Story = {
    // Room above the input, which is where the popover opens.
    render: () => (
        <div className="pt-40">
            <DataframeHintFooter />
        </div>
    ),
}
