import type { Meta, StoryObj } from '@storybook/react'

import { QuillSaveAsDialog } from './QuillSaveAsDialog'
import { SaveAsModal } from './SaveAsModal'
import { SAVE_AS_TARGETS } from './saveAsTargets'
import type { SaveAsTarget, SaveAsTargetMetadata } from './saveAsTargets'

const targets: SaveAsTarget[] = (Object.entries(SAVE_AS_TARGETS) as [SaveAsTarget['id'], SaveAsTargetMetadata][]).map(
    ([id, target], index) => ({
        ...target,
        id,
        recommended: index === 0,
        disabledReason: id === 'endpoint' ? 'Run the latest query changes before saving' : undefined,
        dataAttr: `save-as-${id}`,
    })
)

const meta: Meta<typeof SaveAsModal> = {
    title: 'Scenes/Data warehouse/SQL editor/Save as modal',
    component: SaveAsModal,
    args: {
        isOpen: true,
        targets,
        onClose: () => {},
        onSelect: () => {},
    },
}

export default meta
type Story = StoryObj<typeof SaveAsModal>

export const Lemon: Story = {}

export const Quill: Story = {
    render: (args) => <QuillSaveAsDialog {...args} />,
}
