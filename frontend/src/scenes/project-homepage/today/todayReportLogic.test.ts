import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { fullNameOrEmail } from 'lib/utils/strings'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'

import { todayLogic } from './todayLogic'
import { todayReportLogic } from './todayReportLogic'

const RESOLVER = { id: 99, uuid: 'resolver-uuid', first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' }

describe('todayReportLogic', () => {
    let report: SignalReport

    beforeEach(() => {
        report = makeReport({ id: 'r1', status: SignalReportStatus.RESOLVED, resolved_by: RESOLVER })
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/': () => [200, report],
                '/api/projects/:team_id/signals/reports/:id/signals/': () => [200, { signals: [] }],
            },
            post: {
                '/api/projects/:team_id/signals/reports/:id/state/': () => [200, {}],
            },
        })
        initKeaTests()
        todayLogic.mount()
    })

    const setRailNav = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.TODAY_RAIL_NAV] : [], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: enabled,
        })
    }

    it.each([
        { railNav: true, expected: 'Ada Lovelace' },
        { railNav: false, expected: null },
    ])('names the resolver only behind the rail nav flag ($railNav)', async ({ railNav, expected }) => {
        setRailNav(railNav)
        const logic = todayReportLogic({ reportId: 'r1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.resolvedByName).toEqual(expected)
    })

    it('names the current user right after they resolve from Today', async () => {
        report = makeReport({ id: 'r1', status: SignalReportStatus.READY, resolved_by: null })
        setRailNav(true)
        const logic = todayReportLogic({ reportId: 'r1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.resolvedByName).toBeNull()

        todayLogic.actions.setReportVerdict(
            { reportId: 'r1', title: 'Untitled report', hasOpenPullRequest: false },
            'resolve',
            'report_page'
        )

        expect(logic.values.resolvedByName).toEqual(fullNameOrEmail(MOCK_DEFAULT_USER))
    })
})
