import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLogRow'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

describe('ActivityLogRow', () => {
    afterEach(cleanup)

    beforeEach(() => {
        initKeaTests()
    })

    it.each([false, true])('preserves custom detail tabs with a structured summary: %s', (withSummary) => {
        const logItem: HumanizedActivityLogItem = {
            name: 'peter',
            description: <>changed the rollout</>,
            created_at: dayjs('2022-02-05T16:28:39.594Z'),
            expandedView: { label: 'Release conditions', content: <div>the release conditions</div> },
            summary: withSummary
                ? { actor: <strong>peter</strong>, action: 'Changed the rollout', target: 'onboarding-checklist' }
                : undefined,
        }

        render(
            <Provider>
                <ActivityLogRow logItem={logItem} />
            </Provider>
        )
        fireEvent.click(screen.getByLabelText('Expand activity details'))

        expect(screen.getByText('Release conditions').closest('[role="tab"]')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByText('the release conditions')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Raw'))
        fireEvent.click(screen.getByLabelText('Collapse activity details'))
        fireEvent.click(screen.getByLabelText('Expand activity details'))
        expect(screen.getByText('Raw').closest('[role="tab"]')).toHaveAttribute('aria-selected', 'true')
    })

    it('renders the actor once above the action and keeps the value out of bold text', () => {
        const logItem: HumanizedActivityLogItem = {
            description: 'Mia Chen changed the description to Review workspace setup on Activation overview',
            summary: {
                actor: <strong>Mia Chen</strong>,
                action: 'Updated the description',
                target: 'Activation overview',
                preview: 'Review workspace setup',
            },
            created_at: dayjs(),
            client: 'mcp',
        }
        render(
            <Provider>
                <ActivityLogRow logItem={logItem} />
            </Provider>
        )

        const actor = screen.getByText('Mia Chen')
        const source = screen.getByText('via MCP')
        const action = screen.getByText('Updated the description')
        expect(actor.compareDocumentPosition(source) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(source.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(screen.queryByText(logItem.description as string)).not.toBeInTheDocument()
        expect(screen.getByText('Review workspace setup').closest('strong, b')).toBeNull()
        expect(action).toHaveClass('line-clamp-2')

        fireEvent.click(screen.getByLabelText('Expand activity details'))
        expect(screen.getByText('Diff').closest('[role="tab"]')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByText('This item has no changes to compare')).toBeInTheDocument()
        expect(action).not.toHaveClass('line-clamp-2')
    })

    it('keeps a specialized actor sentence when no structured summary is available', () => {
        render(
            <Provider>
                <ActivityLogRow
                    logItem={{
                        name: 'A user',
                        description: (
                            <>
                                <strong>Anonymous user</strong> authenticated to the shared dashboard
                            </>
                        ),
                        created_at: dayjs(),
                    }}
                />
            </Provider>
        )

        expect(screen.getByText('Anonymous user')).toBeInTheDocument()
        expect(screen.queryByText('A user')).not.toBeInTheDocument()
    })
})
