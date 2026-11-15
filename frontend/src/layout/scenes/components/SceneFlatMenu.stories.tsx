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

import { SceneContentContext } from './SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from './SceneMenuBar'
import { SceneMenuBarSlotProvider } from './SceneMenuBarSlotProvider'
import { SceneTitleSection } from './SceneTitleSection'

type SceneMenuStoryProps = {
    withoutMenuBar?: boolean
    narrow?: boolean
}

function RichSceneMenuBar(): JSX.Element {
    const [favorited, setFavorited] = useState(true)
    const [showSource, setShowSource] = useState(false)
    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="story-menubar-file">
                <SceneMenuBarSubMenu label="Create">
                    <SceneMenuBarItem opensFloatingUi data-attr="story-menubar-add-to-dashboard">
                        <IconPlus />
                        Add to dashboard
                    </SceneMenuBarItem>
                    <SceneMenuBarItem data-attr="story-menubar-subscribe">
                        <IconBell />
                        Subscription
                    </SceneMenuBarItem>
                </SceneMenuBarSubMenu>
                <SceneMenuBarSeparator />
                <SceneMenuBarItem data-attr="story-menubar-copy-to-project">
                    <IconCopy />
                    Copy to another project
                </SceneMenuBarItem>
                <SceneMenuBarItem opensFloatingUi data-attr="story-menubar-terraform">
                    <IconCode2 />
                    Manage with Terraform
                </SceneMenuBarItem>
                <SceneMenuBarSubMenu label="Export">
                    <SceneMenuBarItem data-attr="story-menubar-export-png">
                        <IconDownload />
                        PNG
                    </SceneMenuBarItem>
                    <SceneMenuBarItem data-attr="story-menubar-export-csv">
                        <IconDownload />
                        CSV
                    </SceneMenuBarItem>
                </SceneMenuBarSubMenu>
                <SceneMenuBarSeparator />
                <SceneMenuBarItem variant="destructive" data-attr="story-menubar-delete">
                    <IconTrash />
                    Delete insight
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr="story-menubar-edit">
                <SceneMenuBarItem data-attr="story-menubar-duplicate">
                    <IconCopy />
                    Duplicate
                </SceneMenuBarItem>
                <SceneMenuBarItem data-attr="story-menubar-edit-sql">
                    <IconPencil />
                    Edit in SQL editor
                </SceneMenuBarItem>
                <SceneMenuBarSeparator />
                <SceneMenuBarCheckboxItem checked={favorited} onCheckedChange={setFavorited}>
                    Favorite
                </SceneMenuBarCheckboxItem>
                <SceneMenuBarCheckboxItem checked={showSource} onCheckedChange={setShowSource}>
                    View source
                </SceneMenuBarCheckboxItem>
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="View" dataAttr="story-menubar-view">
                <SceneMenuBarItem data-attr="story-menubar-view-recordings">
                    <IconRewindPlay />
                    View recordings
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
            <SceneMenuBarPopover label="Metadata" dataAttr="story-menubar-metadata">
                <Field>
                    <FieldLabel htmlFor="story-metadata-owner">Owner</FieldLabel>
                    <Input id="story-metadata-owner" placeholder="Add an owner" />
                </Field>
                <Text size="xs" variant="muted">
                    Last modified 3 days ago
                </Text>
            </SceneMenuBarPopover>
        </SceneMenuBar>
    )
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
                    {!withoutMenuBar && <RichSceneMenuBar />}
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
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.SCENE_MENU_BAR],
        testOptions: { waitForSelector: '[data-attr="scene-menu-bar-trigger"]' },
    },
    play: async ({ canvasElement }) => {
        const trigger = canvasElement.querySelector<HTMLElement>('[data-attr="scene-menu-bar-trigger"]')
        if (trigger) {
            await userEvent.click(trigger)
        }
        await within(document.body).findByPlaceholderText('Search actions')
    },
}
export default meta

type Story = StoryObj<typeof SceneMenuStory>

export const RichSceneMenu: Story = {}

export const HelpOnlyFallback: Story = { args: { withoutMenuBar: true } }

export const NarrowScene: Story = { args: { narrow: true } }
