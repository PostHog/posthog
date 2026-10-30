import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { ActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { dashboardActivityDescriber } from './dashboardActivityDescriber'
import { dashboardLogic } from './dashboardLogic'

describe('dashboardActivityDescriber', () => {
    afterEach(cleanup)

    beforeEach(() => {
        initKeaTests()
    })

    const makeLogItem = (after: string | null): ActivityLogItem => ({
        activity: 'updated',
        scope: ActivityScope.DASHBOARD,
        item_id: '42',
        created_at: '2026-09-14T10:00:00Z',
        user: { first_name: 'Mia', last_name: 'Chen', email: 'mia@example.com' },
        detail: {
            name: 'Activation overview',
            merge: null,
            trigger: null,
            changes: [{ type: ActivityScope.DASHBOARD, action: 'changed', field: 'description', after }],
        },
    })

    it.each([
        ['Compare completed setup checklists across new workspaces.', 'added the description'],
        ['', 'cleared the description'],
        [null, 'cleared the description'],
    ])('separates the description preview from the action for %p', (after, action) => {
        const logItem = makeLogItem(after)
        const [item] = humanize([logItem], () => dashboardActivityDescriber, true)

        expect(render(<>{item.summary?.action}</>).container).toHaveTextContent(action)
        expect(item.summary?.preview).toBe(after ?? undefined)
        expect(render(<>{item.summary?.target}</>).getByText('Activation overview')).toHaveAttribute(
            'href',
            expect.stringContaining('/dashboard/42')
        )
        expect(render(<>{item.description}</>).container).toHaveTextContent(
            `Mia Chen changed the description of the dashboard to "${after ?? ''}" on the dashboard Activation overview`
        )
    })

    it('keeps other described changes alongside the preview and omits excluded fields', () => {
        const logItem = makeLogItem('Review workspace setup.')
        logItem.detail.changes!.push(
            { type: ActivityScope.DASHBOARD, action: 'changed', field: 'pinned', before: false, after: true },
            { type: ActivityScope.DASHBOARD, action: 'changed', field: 'last_refresh', after: '2026-09-14' }
        )
        const { summary } = dashboardActivityDescriber(logItem)

        expect(render(<>{summary?.action}</>).container).toHaveTextContent(
            /^added the description, and pinned the dashboard$/
        )
        expect(summary?.preview).toBe('Review workspace setup.')
    })

    it.each(['tiles', 'last_refresh', 'last_accessed_at', undefined])(
        'keeps the fallback row when an update only changes %p',
        (field) => {
            const logItem = makeLogItem(null)
            logItem.detail.changes = field
                ? [{ type: ActivityScope.DASHBOARD, action: 'changed', field, after: null }]
                : []

            for (const asNotification of [false, true]) {
                const [item] = humanize([logItem], () => dashboardActivityDescriber, asNotification)

                expect(item).toBeTruthy()
                expect(item.summary?.action).toBe('Updated')
                expect(render(<>{item.description}</>).container).toHaveTextContent(
                    'Mia Chen updated Activation overview'
                )
            }
        }
    )

    it.each([false, true])('retains a row after a malformed field with prior changes: %p', (hasPriorChange) => {
        const logItem = makeLogItem(null)
        logItem.detail.changes = [{ type: ActivityScope.DASHBOARD, action: 'changed', field: 'filters', after: null }]
        if (hasPriorChange) {
            logItem.detail.changes.unshift({
                type: ActivityScope.DASHBOARD,
                action: 'changed',
                field: 'pinned',
                after: true,
            })
        }
        const consoleError = jest.spyOn(console, 'error').mockImplementation()
        try {
            const [item] = humanize([logItem], () => dashboardActivityDescriber)

            expect(item).toBeTruthy()
            expect(render(<>{item.summary?.action}</>).container).toHaveTextContent(
                hasPriorChange ? /^pinned the dashboard$/ : /^Updated$/
            )
            expect(render(<>{item.description}</>).container).toHaveTextContent(
                hasPriorChange ? 'Mia Chen pinned Activation overview' : 'Mia Chen updated Activation overview'
            )
        } finally {
            consoleError.mockRestore()
        }
    })

    it.each([false, true])('keeps both dashboard names in the headline with notifications: %p', (asNotification) => {
        const logItem = makeLogItem(null)
        logItem.detail.changes = [
            {
                type: ActivityScope.DASHBOARD,
                action: 'changed',
                field: 'name',
                before: 'Workspace setup',
                after: 'Activation overview',
            },
        ]
        const { summary } = dashboardActivityDescriber(logItem, asNotification)

        expect(render(<>{summary?.action}</>).container).toHaveTextContent(
            /^renamed "Workspace setup" to "Activation overview"$/
        )
        expect(render(<>{summary?.target}</>).getByText('Activation overview')).toHaveAttribute(
            'href',
            expect.stringContaining('/dashboard/42')
        )
    })

    it.each([
        [{ user: { first_name: '', last_name: '', email: 'mia@example.com' } }, 'mia@example.com'],
        [{ is_system: true }, 'PostHog'],
        [{ activity: 'share_login_success' }, 'Anonymous user'],
        [{ activity: 'share_login_failed' }, 'Anonymous user'],
        [{ was_impersonated: true }, 'PostHog Support (as Mia Chen)'],
    ])('preserves actor attribution in summaries for %p', (overrides, name) => {
        const { summary } = dashboardActivityDescriber({ ...makeLogItem('Review setup.'), ...overrides })

        expect(render(<>{summary?.actor}</>).container).toHaveTextContent(name)
    })

    it('provides a creation summary without a value preview', () => {
        const { summary, description } = dashboardActivityDescriber({
            ...makeLogItem(null),
            activity: 'created',
        })

        expect(summary?.action).toBe('Created the dashboard')
        expect(summary?.preview).toBeUndefined()
        expect(render(<>{description}</>).container).toHaveTextContent(
            'Mia Chen created the dashboard Activation overview'
        )
    })
    it.each([true, false])('describes a layout change, offering a restore when the undo flag is %s', async (flagOn) => {
        featureFlagLogic.actions.setFeatureFlags(flagOn ? [FEATURE_FLAGS.DASHBOARD_LAYOUT_UNDO] : [], {
            [FEATURE_FLAGS.DASHBOARD_LAYOUT_UNDO]: flagOn,
        })
        const restoreTilePlacements = jest.fn()
        const logic = { actions: { restoreTilePlacements } }
        jest.spyOn(dashboardLogic, 'findMounted').mockReturnValue(logic as any)
        const logItem: ActivityLogItem = {
            ...makeLogItem(null),
            detail: {
                name: 'Activation overview',
                merge: null,
                trigger: null,
                changes: [
                    {
                        type: ActivityScope.DASHBOARD,
                        action: 'changed',
                        field: 'tile_layouts',
                        before: {
                            '7': { layouts: { sm: { x: 0, y: 0, w: 6, h: 5 } }, group_key: null },
                            '8': { layouts: { sm: { x: 6, y: 0, w: 6, h: 5 } }, group_key: null },
                        },
                        after: {
                            '7': { layouts: { sm: { x: 6, y: 0, w: 6, h: 5 } }, group_key: null },
                            '8': { layouts: { sm: { x: 6, y: 0, w: 6, h: 5 } }, group_key: null },
                        },
                    },
                ],
            },
        }
        const [item] = humanize([logItem], () => dashboardActivityDescriber, false)
        const { container, getByText, queryByText } = render(<>{item.description}</>)

        expect(container).toHaveTextContent('rearranged 1 tile')
        if (!flagOn) {
            expect(queryByText('Restore previous layout')).not.toBeInTheDocument()
            return
        }
        fireEvent.click(getByText('Restore previous layout'))

        await waitFor(() =>
            expect(restoreTilePlacements).toHaveBeenCalledWith({
                7: { layouts: { sm: { x: 0, y: 0, w: 6, h: 5 } }, group_key: null },
                8: { layouts: { sm: { x: 6, y: 0, w: 6, h: 5 } }, group_key: null },
            })
        )
        expect(dashboardLogic.findMounted).toHaveBeenCalledWith({ id: 42 })
    })
})
