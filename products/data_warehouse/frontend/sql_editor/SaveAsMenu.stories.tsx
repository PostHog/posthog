import type { Meta, StoryObj } from '@storybook/react'

import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { LemonSaveAsMenuContent } from './LemonSaveAsMenu'
import { QuillSaveAsMenuItems } from './QuillSaveAsMenu'
import { SAVE_AS_TARGETS } from './saveAsTargets'
import type { SaveAsTarget, SaveAsTargetMetadata } from './saveAsTargets'

const targets: SaveAsTarget[] = (Object.entries(SAVE_AS_TARGETS) as [SaveAsTarget['id'], SaveAsTargetMetadata][]).map(
    ([id, target], index) => ({
        ...target,
        id,
        recommended: index === 0,
        disabledReason:
            id === 'endpoint'
                ? 'Run the current query successfully to check which columns the endpoint will return'
                : undefined,
        dataAttr: `save-as-${id}`,
    })
)

const meta: Meta<typeof LemonSaveAsMenuContent> = {
    title: 'Scenes/Data warehouse/SQL editor/Save as menu',
    component: LemonSaveAsMenuContent,
    args: {
        targets,
        onSelect: () => {},
    },
    // The menu opens leftwards from a right-aligned trigger, so the box keeps the whole menu inside the snapshot.
    decorators: [
        (Story) => (
            <div className="flex h-[30rem] w-[22rem] items-start justify-end">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof LemonSaveAsMenuContent>

export const Lemon: Story = {
    render: (args) => (
        <LemonDropdown
            startVisible
            placement="bottom-end"
            className="w-80"
            overlay={<LemonSaveAsMenuContent {...args} />}
            closeOnClickInside
        >
            <LemonButton type="primary">Save as</LemonButton>
        </LemonDropdown>
    ),
}

export const Quill: Story = {
    render: (args) => (
        <DropdownMenu defaultOpen>
            <DropdownMenuTrigger render={<Button variant="primary" />}>Save as</DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80" data-attr="sql-editor-save-as-dialog">
                <QuillSaveAsMenuItems {...args} />
            </DropdownMenuContent>
        </DropdownMenu>
    ),
}
