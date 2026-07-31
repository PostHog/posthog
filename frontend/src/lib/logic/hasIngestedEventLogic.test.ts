import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { hasIngestedEventLogic } from './hasIngestedEventLogic'

describe('hasIngestedEventLogic', () => {
    let logic: ReturnType<typeof hasIngestedEventLogic.build>

    function mount(ingestedEvent: boolean): void {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: ingestedEvent })
        logic = hasIngestedEventLogic()
        logic.mount()
    }

    afterEach(() => {
        logic?.unmount()
    })

    it('reflects `currentTeam.ingested_event` when no real data has been observed', async () => {
        mount(false)
        await expectLogic(logic).toMatchValues({ hasIngestedEvent: false })
    })

    it('flips to true once a scene reports real data, even while the team flag still lags', async () => {
        mount(false)

        await expectLogic(logic, () => {
            logic.actions.reportRealDataObserved()
        }).toMatchValues({ hasIngestedEvent: true })
    })

    it('refreshes the team when real data is observed before the flag has caught up', async () => {
        mount(false)

        await expectLogic(logic, () => {
            logic.actions.reportRealDataObserved()
        }).toDispatchActions(['reportRealDataObserved', teamLogic.actionTypes.loadCurrentTeam])
    })

    it('does not re-fetch the team when it already reflects ingestion', async () => {
        mount(true)

        await expectLogic(logic, () => {
            logic.actions.reportRealDataObserved()
        }).toNotHaveDispatchedActions([teamLogic.actionTypes.loadCurrentTeam])
    })
})
