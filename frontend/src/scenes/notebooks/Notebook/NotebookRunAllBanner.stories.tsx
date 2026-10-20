import { Meta, StoryObj } from '@storybook/react'

import { NotebookRunAllBanner } from './NotebookRunAllBanner'
import { notebookRunLogic } from './notebookRunLogic'

const SHORT_ID = 'runall01'

const runStatus = (currentIndex: number, cellCount: number): any => ({
    run_id: 'nbrun-1',
    status: 'running',
    trigger: 'ui',
    variables: [],
    cell_count: cellCount,
    current_index: currentIndex,
    current_node_id: 'n1',
    failed_node_id: null,
    error: null,
    cells: [],
    created_at: '2026-01-01T00:00:00Z',
    finished_at: null,
})

/** Seeds the logic the banner reads, so each story shows one state without a live run.
 *
 * Both actions are plain reducer writes. `startRun` would be the truer trigger, but it posts
 * to the run endpoint, and the failure that follows in a story clears the state again.
 */
const withRun = (run: any | null) => {
    return function Decorator(Story: () => JSX.Element): JSX.Element {
        const logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()
        if (run) {
            logic.actions.setRun(run)
        } else {
            logic.actions.setStarting(true)
        }
        return <Story />
    }
}

const meta: Meta<typeof NotebookRunAllBanner> = {
    title: 'Scenes-App/Notebooks/Run all banner',
    component: NotebookRunAllBanner,
    args: { shortId: SHORT_ID },
    // The banner sits above the document, which is narrow when a side panel is open.
    decorators: [
        (Story) => (
            <div className="w-[32rem]">
                <Story />
            </div>
        ),
    ],
    parameters: {
        layout: 'padded',
        // The banner only exists while a run is in flight, so its spinner never stops. Without
        // this the snapshot runner waits for every loader to disappear and times out.
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof NotebookRunAllBanner>

export const Starting: Story = {
    decorators: [withRun(null)],
}

export const MidRun: Story = {
    decorators: [withRun(runStatus(2, 8))],
}

export const LastCell: Story = {
    decorators: [withRun(runStatus(7, 8))],
}
