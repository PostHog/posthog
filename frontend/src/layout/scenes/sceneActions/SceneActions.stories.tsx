import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import {
    IconBell,
    IconCode2,
    IconCopy,
    IconDownload,
    IconPencil,
    IconPlus,
    IconRewindPlay,
    IconTrash,
} from '@posthog/icons'
import { Field, FieldLabel, Input, Text, cn } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { SceneContentContext } from '../components/SceneContent'
import { SceneMenuBarSlotProvider } from '../components/SceneMenuBarSlotProvider'
import { SceneTitleSection } from '../components/SceneTitleSection'
import { SCENE_ACTIONS_TRIGGER_DATA_ATTR } from './SceneActionMenu'
import type { SceneAction } from './sceneActionModel'
import { SceneActions } from './SceneActions'

type SceneMenuStoryProps = {
    withoutMenuBar?: boolean
    narrow?: boolean
}

const noop = (): void => {}

function RichSceneActions(): JSX.Element {
    const [favorited, setFavorited] = useState(true)
    const [showSource, setShowSource] = useState(false)
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            type: 'submenu',
            id: 'story-menubar-create',
            label: 'Create',
            icon: <IconPlus />,
            items: [
                {
                    id: 'story-menubar-add-to-dashboard',
                    label: 'Add to dashboard',
                    icon: <IconPlus />,
                    opensFloatingUi: true,
                    onSelect: noop,
                },
            ],
        },
        {
            group: 'file',
            section: 'share',
            id: 'story-menubar-subscribe',
            label: 'Subscribe',
            icon: <IconBell />,
            onSelect: noop,
            pinned: { order: 2, variant: 'secondary' },
        },
        {
            group: 'file',
            section: 'project',
            id: 'story-menubar-copy-to-project',
            label: 'Copy to another project',
            icon: <IconCopy />,
            onSelect: noop,
        },
        {
            group: 'file',
            section: 'project',
            id: 'story-menubar-terraform',
            label: 'Manage with Terraform',
            icon: <IconCode2 />,
            opensFloatingUi: true,
            onSelect: noop,
        },
        {
            group: 'file',
            section: 'project',
            type: 'submenu',
            id: 'story-menubar-export',
            label: 'Export',
            icon: <IconDownload />,
            items: [
                { id: 'story-menubar-export-png', label: 'PNG', icon: <IconDownload />, onSelect: noop },
                { id: 'story-menubar-export-csv', label: 'CSV', icon: <IconDownload />, onSelect: noop },
            ],
        },
        {
            group: 'file',
            section: 'delete',
            id: 'story-menubar-delete',
            label: 'Delete insight',
            icon: <IconTrash />,
            destructive: true,
            onSelect: noop,
        },
        {
            group: 'edit',
            id: 'story-menubar-edit',
            label: 'Edit',
            icon: <IconPencil />,
            onSelect: noop,
            pinned: { order: 1, variant: 'primary' },
        },
        { group: 'edit', id: 'story-menubar-duplicate', label: 'Duplicate', icon: <IconCopy />, onSelect: noop },
        {
            group: 'edit',
            section: 'toggles',
            type: 'checkbox',
            id: 'story-menubar-favorite',
            label: 'Favorite',
            checked: favorited,
            onCheckedChange: setFavorited,
        },
        {
            group: 'edit',
            section: 'toggles',
            type: 'checkbox',
            id: 'story-menubar-view-source',
            label: 'View source',
            checked: showSource,
            onCheckedChange: setShowSource,
        },
        {
            group: 'view',
            id: 'story-menubar-view-recordings',
            label: 'View recordings',
            icon: <IconRewindPlay />,
            onSelect: noop,
            pinned: { order: 3, variant: 'secondary' },
        },
        {
            group: 'metadata',
            type: 'panel',
            id: 'story-menubar-metadata',
            label: 'Metadata',
            render: () => (
                <>
                    <Field>
                        <FieldLabel htmlFor="story-metadata-owner">Owner</FieldLabel>
                        <Input id="story-metadata-owner" placeholder="Add an owner" />
                    </Field>
                    <Text size="xs" variant="muted">
                        Last modified 3 days ago
                    </Text>
                </>
            ),
        },
    ]
    return <SceneActions actions={actions} dataAttrKey="story" />
}

function SceneMenuStory({ withoutMenuBar = false, narrow = false }: SceneMenuStoryProps): JSX.Element {
    return (
        <SceneContentContext.Provider value={{ productKey: ProductKey.PRODUCT_ANALYTICS }}>
            <SceneMenuBarSlotProvider>
                <div
                    data-quill
                    className={cn(
                        '@container/main-content min-h-120 bg-[var(--scene-layout-background)] p-4',
                        narrow && 'w-130'
                    )}
                >
                    {!withoutMenuBar && <RichSceneActions />}
                    <SceneTitleSection name="Weekly active users by country" resourceType={{ type: 'insight' }} />
                </div>
            </SceneMenuBarSlotProvider>
        </SceneContentContext.Provider>
    )
}

const meta: Meta<typeof SceneMenuStory> = {
    title: 'Layout/Scene menu',
    component: SceneMenuStory,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.SCENE_MENU_BAR, FEATURE_FLAGS.SCENE_ACTIONS],
        testOptions: { waitForSelector: `[data-attr="${SCENE_ACTIONS_TRIGGER_DATA_ATTR}"]` },
    },
    play: async ({ canvasElement, parameters }) => {
        const trigger = canvasElement.querySelector<HTMLElement>(`[data-attr="${SCENE_ACTIONS_TRIGGER_DATA_ATTR}"]`)
        if (trigger) {
            await userEvent.click(trigger)
        }
        await within(document.body).findByRole('menu')
        const query: string | undefined = parameters.menuQuery
        if (query) {
            await userEvent.type(within(document.body).getByPlaceholderText('Search actions'), query)
        }
        const panelRow: string | undefined = parameters.menuPanelRow
        if (panelRow) {
            await userEvent.click(within(document.body).getByText(panelRow))
            await within(document.body).findByPlaceholderText('Add an owner')
        }
    },
}
export default meta

type Story = StoryObj<typeof SceneMenuStory>

export const RichSceneMenu: Story = {}

export const SearchResults: Story = { parameters: { menuQuery: 're' } }

// The Metadata row closes the menu and opens its content in a popover, where text inputs work.
export const MetadataPanel: Story = {
    parameters: { menuPanelRow: 'Metadata', testOptions: { waitForSelector: '[placeholder="Add an owner"]' } },
}

export const SearchWithNoMatches: Story = { parameters: { menuQuery: 'zzqx' } }

export const HelpOnlyFallback: Story = { args: { withoutMenuBar: true } }

export const NarrowScene: Story = { args: { narrow: true } }

// With `scene-actions` off the same list renders through the menu bar primitives, as scenes did before.
export const WithoutSceneActionsFlag: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.SCENE_MENU_BAR] },
}
