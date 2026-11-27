import type { Meta, StoryObj } from '@storybook/react'
import { createRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { DetailPanel } from './DetailPanel'

const SCENE_TOP = 56
const SCENE_HEIGHT = 560

function sceneRect(width: number): { top: number; right: number; height: number; width: number } {
    return { top: SCENE_TOP, right: window.innerWidth, height: SCENE_HEIGHT, width }
}

function Body({ paragraphs }: { paragraphs: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {Array.from({ length: paragraphs }, (_, index) => (
                <p key={index} className="m-0">
                    Step {index + 1}: the model received the request, called a tool and returned an answer.
                </p>
            ))}
        </div>
    )
}

const meta: Meta<typeof DetailPanel> = {
    title: 'Scenes-App/AI observability/Shared/Detail panel',
    component: DetailPanel,
    parameters: { testOptions: { snapshotTargetSelector: 'aside' } },
    args: {
        toolbar: <span className="font-semibold">Toolbar</span>,
        children: <Body paragraphs={4} />,
        width: 640,
        resizer: null,
        containerRef: createRef<HTMLElement>(),
        'aria-label': 'Trace detail',
        'data-attr': 'detail-panel',
        rect: sceneRect(1000),
    },
}
export default meta

type Story = StoryObj<typeof DetailPanel>

export const Default: Story = {}

export const Narrow: Story = {
    args: { rect: sceneRect(640), toolbar: <LemonButton size="small">Close</LemonButton> },
}

export const LongBody: Story = {
    args: { children: <Body paragraphs={40} /> },
}
