import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { ticketActivityDescriber } from './activityDescriber'

// WorkflowActivityLink resolves the workflow name from workflowsLogic; stub it so the describer
// tests stay pure. Its own name-resolution behavior is covered in WorkflowActivityLink.test.tsx.
jest.mock('./WorkflowActivityLink', () => ({
    WorkflowActivityLink: ({ id }: { id: string }) => <span>workflow-actor:{id}</span>,
}))

const getTextContent = (describer: { description: JSX.Element | string | null }): string => {
    if (!describer.description || typeof describer.description === 'string') {
        return (describer.description as string) || ''
    }
    const { container } = render(describer.description)
    return container.textContent || ''
}

const ticketLogItem = (overrides: Partial<ActivityLogItem>): ActivityLogItem => ({
    activity: 'updated',
    created_at: '2026-06-25T10:00:00Z',
    scope: 'Ticket',
    item_id: 'ticket-uuid',
    detail: { merge: null, trigger: null, changes: null, name: 'Ticket #2043' },
    ...overrides,
})

describe('ticketActivityDescriber', () => {
    const statusChange: ActivityChange = {
        type: ActivityScope.TICKET,
        action: 'changed',
        field: 'status',
        before: 'new',
        after: 'open',
    }
    const snoozeCleared: ActivityChange = {
        type: ActivityScope.TICKET,
        action: 'changed',
        field: 'snoozed_until',
        before: '2026-06-25T10:00:00Z',
        after: null,
    }
    const reopened: ActivityChange = {
        type: ActivityScope.TICKET,
        action: 'changed',
        field: 'status',
        before: 'on_hold',
        after: 'open',
    }

    it('attributes a workflow-triggered change to the workflow, not PostHog', () => {
        const result = ticketActivityDescriber(
            ticketLogItem({
                detail: {
                    merge: null,
                    name: 'Ticket #2043',
                    changes: [statusChange],
                    trigger: { job_type: 'hog_flow', job_id: 'flow-123', payload: {} },
                },
            })
        )
        const text = getTextContent(result)
        expect(text).toContain('workflow-actor:flow-123')
        expect(text).toContain('changed status')
        expect(text).not.toContain('PostHog')
    })

    it('attributes a non-workflow change to the acting user', () => {
        const result = ticketActivityDescriber(
            ticketLogItem({
                user: { email: 'max@posthog.com', first_name: 'Max', last_name: 'AI' },
                detail: { merge: null, trigger: null, name: 'Ticket #2043', changes: [statusChange] },
            })
        )
        expect(getTextContent(result)).toContain('Max AI')
    })

    it('describes a workflow-driven snooze clear as "removed snooze", not "snooze expired"', () => {
        const result = ticketActivityDescriber(
            ticketLogItem({
                detail: {
                    merge: null,
                    name: 'Ticket #2043',
                    changes: [snoozeCleared],
                    trigger: { job_type: 'hog_flow', job_id: 'flow-123', payload: {} },
                },
            })
        )
        const text = getTextContent(result)
        expect(text).toContain('workflow-actor:flow-123')
        expect(text).toContain('removed snooze')
        expect(text).not.toContain('snooze expired')
    })

    it('describes a manual unsnooze (user present) as "removed snooze"', () => {
        const result = ticketActivityDescriber(
            ticketLogItem({
                user: { email: 'max@posthog.com', first_name: 'Max', last_name: 'AI' },
                detail: { merge: null, trigger: null, name: 'Ticket #2043', changes: [snoozeCleared] },
            })
        )
        const text = getTextContent(result)
        expect(text).toContain('removed snooze')
        expect(text).not.toContain('snooze expired')
    })

    it('describes a system snooze-expiry (no user) as "snooze expired – reopened"', () => {
        const result = ticketActivityDescriber(
            ticketLogItem({
                detail: { merge: null, trigger: null, name: 'Ticket #2043', changes: [snoozeCleared, reopened] },
            })
        )
        const text = getTextContent(result)
        expect(text).toContain('snooze expired')
        expect(text).toContain('reopened')
    })

    it('describes a system snooze-expiry with no status change as "snooze expired" (not reopened)', () => {
        const result = ticketActivityDescriber(
            ticketLogItem({
                detail: { merge: null, trigger: null, name: 'Ticket #3', changes: [snoozeCleared] },
            })
        )
        const text = getTextContent(result)
        expect(text).toContain('snooze expired')
        expect(text).not.toContain('reopened')
    })
})
