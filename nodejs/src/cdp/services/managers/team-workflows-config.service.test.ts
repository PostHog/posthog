import { createTestTeamFixture } from '~/tests/helpers/sql'

import { closeHub, createHub } from '../../../common/utils/db/hub'
import { Hub, Team } from '../../../types'
import { TeamWorkflowsConfigService } from './team-workflows-config.service'

describe('TeamWorkflowsConfigService', () => {
    let hub: Hub
    let team: Team
    let service: TeamWorkflowsConfigService

    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team
        service = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('fails closed when the engagement capture lookup errors', async () => {
        jest.spyOn(service, 'get').mockRejectedValueOnce(new Error('pg down'))

        await expect(service.shouldCaptureEngagementEvents(team.id)).resolves.toBe(false)
    })
})
