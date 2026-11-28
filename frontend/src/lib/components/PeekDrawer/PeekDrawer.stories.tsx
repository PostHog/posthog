import type { Meta, StoryObj } from '@storybook/react'

import { IconArrowRight, IconPin } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { PeekDrawer } from './PeekDrawer'

const meta: Meta<typeof PeekDrawer> = {
    title: 'Components/Peek drawer',
    component: PeekDrawer,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // The drawer slides in on open, so a snapshot can catch it mid-transition. The runner still renders it.
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof PeekDrawer>

export const Open: Story = {
    args: {
        open: true,
        onClose: () => {},
        title: 'Checkout conversion',
        'data-attr': 'peek-drawer-story',
        actions: (
            <>
                <Button size="icon-sm" aria-label="Pin">
                    <IconPin />
                </Button>
                <Button size="sm" variant="outline">
                    View
                    <IconArrowRight />
                </Button>
            </>
        ),
        children: (
            <div className="flex flex-col gap-2">
                {Array.from({ length: 40 }, (_, index) => (
                    <p key={index}>Row {index + 1} of the item's content</p>
                ))}
            </div>
        ),
    },
}
