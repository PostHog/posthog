import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TicketPatternApi } from '../../generated/api.schemas'
import { ticketPatternsLogic } from './ticketPatternsLogic'

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

describe('ticketPatternsLogic', () => {
    let logic: ReturnType<typeof ticketPatternsLogic.build>

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
        logic = ticketPatternsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadOpenPatternsSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
    })

    it('removes the row on dismiss and restores it when the request fails', async () => {
        await expectLogic(logic, () => logic.actions.dismissPattern('a')).toMatchValues({
            openPatterns: [makePattern('b')],
            inFlightIds: ['a'],
        })

        await expectLogic(logic)
            .toDispatchActions(['restorePattern', 'decisionFailed'])
            .toMatchValues({ inFlightIds: [] })

        expect(logic.values.openPatterns.map((p) => p.id).sort()).toEqual(['a', 'b'])
    })

    it('keeps the row gone once the server confirms', async () => {
        await expectLogic(logic, () => logic.actions.confirmPattern('b'))
            .toDispatchActions(['decisionSucceeded'])
            .toMatchValues({ inFlightIds: [] })

        expect(logic.values.openPatterns.map((p) => p.id)).toEqual(['a'])
    })
})
