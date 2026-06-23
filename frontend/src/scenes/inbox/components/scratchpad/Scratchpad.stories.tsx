import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { mswDecorator } from '~/mocks/browser'

import { scratchpadEntries } from '../../__mocks__/scratchpadMocks'
import { FleetMemoryCallout } from '../config/scouts/FleetMemoryCallout'
import { ScratchpadPanel } from './ScratchpadPanel'

// Prototype for the scout "fleet memory" UI: a callout in the scouts list that opens a
// browse/search surface over the durable scratchpad. Driven by mocked entries through the real
// read endpoint (`/signals/scout/scratchpad/`), so search filtering exercises the live code path.

const SCRATCHPAD_PATH = '/api/projects/:id/signals/scout/scratchpad/'

// Match the endpoint's server-side ILIKE on key + content so typing in the story filters for real.
function searchEntries(text: string | null): typeof scratchpadEntries {
    if (!text) {
        return scratchpadEntries
    }
    const needle = text.toLowerCase()
    return scratchpadEntries.filter(
        (entry) => entry.key.toLowerCase().includes(needle) || entry.content.toLowerCase().includes(needle)
    )
}

const populatedMocks = mswDecorator({
    get: {
        [SCRATCHPAD_PATH]: ({ request }) => [200, searchEntries(new URL(request.url).searchParams.get('text'))],
    },
})

const emptyMocks = mswDecorator({
    get: {
        [SCRATCHPAD_PATH]: () => [200, []],
    },
})

const meta: Meta = {
    title: 'Scenes-App/Inbox/Scout memory',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-06-23',
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [populatedMocks],
}
export default meta

type Story = StoryObj

/** The full browse/search surface with a populated fleet memory. Type in the search box to filter. */
export const Panel: Story = {
    render: () => (
        <div className="max-w-3xl">
            <ScratchpadPanel />
        </div>
    ),
}

/** Fresh project: the fleet hasn't written anything yet. */
export const PanelEmpty: Story = {
    decorators: [emptyMocks],
    render: () => (
        <div className="max-w-3xl">
            <ScratchpadPanel />
        </div>
    ),
}

/** Just the callout card as it sits in the scouts troop list. */
export const Callout: Story = {
    render: () => (
        <div className="max-w-xl">
            <FleetMemoryCallout onOpen={() => undefined} />
        </div>
    ),
}

/** End-to-end click flow: the callout in the scouts list opens the scratchpad surface. */
export const CalloutToPanel: Story = {
    render: () => {
        const [open, setOpen] = useState(false)
        return (
            <div className="max-w-3xl">
                {open ? (
                    <div className="flex flex-col gap-2">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconArrowLeft />}
                            onClick={() => setOpen(false)}
                            className="self-start"
                        >
                            Scouts
                        </LemonButton>
                        <ScratchpadPanel />
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        <span className="text-xs uppercase tracking-wide text-muted">Scout troop</span>
                        <FleetMemoryCallout onOpen={() => setOpen(true)} />
                    </div>
                )}
            </div>
        )
    },
}
