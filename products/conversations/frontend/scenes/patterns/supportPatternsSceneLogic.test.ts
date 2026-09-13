import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ticketPatternsLogic } from '../../components/TicketPatterns/ticketPatternsLogic'
import type { TicketPatternApi } from '../../generated/api.schemas'
import { type PatternStatusFilter, supportPatternsSceneLogic } from './supportPatternsSceneLogic'

function makePattern(id: string): TicketPatternApi {
    return {
        id,
        topic: 'login',
        source: 'terms',
        title: `pattern ${id}`,
        summary: '',
        status: 'open',
        severity: 'medium',
        ticket_count: 6,
        requester_count: 6,
        peak_ticket_count: 6,
        first_ticket_at: '2026-01-01T10:00:00Z',
        opened_at: '2026-01-01T10:15:00Z',
        last_seen_at: '2026-01-01T10:15:00Z',
        resolved_at: null,
        resolved_by: null,
        owner: null,
        evidence: {},
        tickets: [],
    }
}

describe('supportPatternsSceneLogic', () => {
    let logic: ReturnType<typeof supportPatternsSceneLogic.build>

    beforeEach(async () => {
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/patterns/': () => [
                    200,
                    { results: [makePattern('a'), makePattern('b')], count: 2, next: null, previous: null },
                ],
            },
            post: {
                '/api/projects/:team_id/conversations/patterns/a/dismiss/': () => [500, { detail: 'boom' }],
                '/api/projects/:team_id/conversations/patterns/b/confirm/': () => [
                    200,
                    { ...makePattern('b'), status: 'confirmed' },
                ],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS], {
            [FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS]: true,
        })
        logic = supportPatternsSceneLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
    })

    it.each([
        { statusFilter: 'open' as PatternStatusFilter, visible: ['a'] },
        { statusFilter: 'all' as PatternStatusFilter, visible: ['a', 'b'] },
    ])('confirming under the $statusFilter filter leaves $visible visible', async ({ statusFilter, visible }) => {
        if (statusFilter !== 'open') {
            logic.actions.setStatusFilter(statusFilter)
            await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])
        }

        ticketPatternsLogic.actions.confirmPattern('b')
        await expectLogic(ticketPatternsLogic).toDispatchActions(['decisionSucceeded'])

        expect(logic.values.visiblePatterns.map((p) => p.id)).toEqual(visible)
    })

    it('ignores a response for the filter the person left', async () => {
        let releaseConfirmed = (): void => {}
        const confirmedHeld = new Promise<void>((resolve) => {
            releaseConfirmed = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/patterns/': async ({ request }) => {
                    const status = new URL(request.url).searchParams.get('status')
                    if (status === 'confirmed') {
                        await confirmedHeld
                        return [200, { results: [makePattern('stale')], count: 1, next: null, previous: null }]
                    }
                    return [200, { results: [makePattern('fresh')], count: 1, next: null, previous: null }]
                },
            },
        })

        logic.actions.setStatusFilter('confirmed')
        logic.actions.setStatusFilter('dismissed')
        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])

        releaseConfirmed()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.patterns.map((p) => p.id)).toEqual(['fresh'])
    })

    it('opens on the filter the ticket panel linked to', async () => {
        logic.unmount()
        router.actions.push(urls.supportPatterns('confirmed'))
        logic = supportPatternsSceneLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])

        expect(logic.values.statusFilter).toEqual('confirmed')
    })

    it('goes back to the default filter when the URL drops the status', async () => {
        logic.actions.setStatusFilter('confirmed')
        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])

        router.actions.push(urls.supportPatterns())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.statusFilter).toEqual('open')
    })

    it('loads nothing when the feature flag is off', async () => {
        logic.unmount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        logic = supportPatternsSceneLogic()
        logic.mount()

        await expectLogic(logic).toNotHaveDispatchedActions(['loadPatterns'])
    })

    it('puts the row back when the decision fails', async () => {
        ticketPatternsLogic.actions.dismissPattern('a')
        await expectLogic(logic).toMatchValues({ visiblePatterns: [makePattern('b')] })

        await expectLogic(ticketPatternsLogic).toDispatchActions(['decisionFailed'])

        expect(logic.values.visiblePatterns.map((p) => p.id)).toEqual(['a', 'b'])
    })
})
