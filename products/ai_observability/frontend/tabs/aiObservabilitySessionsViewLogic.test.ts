import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiObservabilitySessionsViewLogic } from './aiObservabilitySessionsViewLogic'

describe('aiObservabilitySessionsViewLogic', () => {
    it('leaves the trace drawer params behind when selecting a session', () => {
        useMocks({ post: { '/api/environments/:team_id/query/:kind/': () => [200, { results: [] }] } })
        initKeaTests()
        router.actions.push(`${urls.aiObservabilitySessions()}?date_from=-7d&trace=a&ts=2026&step=x`)
        const logic = aiObservabilitySessionsViewLogic()
        logic.mount()

        logic.actions.selectSession('session-1')

        expect(router.values.location.pathname).toContain(urls.aiObservabilitySession('session-1'))
        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
        logic.unmount()
    })
})
