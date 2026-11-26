import type { Meta, StoryObj } from '@storybook/react'

import { ready } from '../../traces/testFixtures'
import { makeSessionListItem, makeSessionPersonItem, makeSessionPreview } from '../testFixtures'
import { SessionListRow } from './SessionListRow'

const item = makeSessionListItem()

const meta: Meta<typeof SessionListRow> = {
    title: 'Scenes-App/AI observability/Sessions/Session list row',
    component: SessionListRow,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        item,
        title: ready(makeSessionPreview(item.id)),
        person: ready(makeSessionPersonItem(item.id).person),
        isOpen: false,
        href: '/ai-observability/sessions?session=session-1',
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-75 overflow-hidden border rounded">
                <table className="w-full">
                    <tbody>
                        <tr>
                            <td>
                                <StoryComponent />
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SessionListRow>

export const Ready: Story = {}

export const Open: Story = { args: { isOpen: true } }

export const Loading: Story = { args: { title: { status: 'loading' }, person: { status: 'loading' } } }

export const Untitled: Story = {
    args: { title: ready(makeSessionPreview(item.id, { input: null, inputMissingReason: null })) },
}

export const LongTitle: Story = {
    args: {
        title: ready(
            makeSessionPreview(item.id, {
                input: 'Summarize this paragraph in one line: the quick brown fox jumps over the lazy dog.',
            })
        ),
    },
}

export const FailedCells: Story = { args: { title: { status: 'error' }, person: { status: 'error' } } }

export const SingleTurn: Story = { args: { item: makeSessionListItem({ turnCount: 1, durationMs: null }) } }
