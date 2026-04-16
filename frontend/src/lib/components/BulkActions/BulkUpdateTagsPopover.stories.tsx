import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Popover } from 'lib/lemon-ui/Popover'
import { BulkTagAction, listSelectionLogic } from 'lib/logic/listSelectionLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { BulkUpdateTagsPopover } from './BulkUpdateTagsPopover'

const RESOURCE = 'feature_flags' as const

const meta: Meta<typeof BulkUpdateTagsPopover> = {
    title: 'Components/BulkUpdateTagsPopover',
    component: BulkUpdateTagsPopover,
    parameters: {
        layout: 'centered',
    },
}
export default meta

type Story = StoryObj<typeof BulkUpdateTagsPopover>

function MockedPopover({ action }: { action: BulkTagAction }): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/tags': ['production', 'staging', 'beta', 'internal'],
        },
    })
    const { setSelectedIds, setPopoverTagAction, setPopoverSelectedTags } = useActions(
        listSelectionLogic({ resource: RESOURCE })
    )

    useDelayedOnMountEffect(() => {
        setSelectedIds([1, 2, 3])
        setPopoverTagAction(action)
        setPopoverSelectedTags(['production', 'beta'])
    }, 10)

    return (
        <Popover visible overlay={<BulkUpdateTagsPopover resource={RESOURCE} />}>
            <LemonButton type="secondary" size="small">
                Update tags
            </LemonButton>
        </Popover>
    )
}

export const AddMode: Story = {
    render: () => <MockedPopover action="add" />,
}

export const RemoveMode: Story = {
    render: () => <MockedPopover action="remove" />,
}

export const ReplaceMode: Story = {
    render: () => <MockedPopover action="set" />,
}
