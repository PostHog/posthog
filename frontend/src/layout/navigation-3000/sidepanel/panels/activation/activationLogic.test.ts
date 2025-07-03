import { expectLogic } from 'kea-test-utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { activationLogic, ActivationTask } from './activationLogic'

describe('activationLogic', () => {
    let logic: ReturnType<typeof activationLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = activationLogic()
        logic.mount()
        await expectLogic(logic).toMount([inviteLogic, membersLogic, teamLogic])
    })

    afterEach(() => logic.unmount())

    it('should load custom events on mount', async () => {
        expectLogic(logic).toDispatchActions(['loadCustomEvents', 'loadInsights'])
    })

    describe('expandedTaskId functionality', () => {
        it('should set and clear expanded task id', () => {
            const taskId = ActivationTask.IngestFirstEvent

            expectLogic(logic, () => {
                logic.actions.setExpandedTaskId(taskId)
            }).toMatchValues({
                expandedTaskId: taskId,
            })

            expectLogic(logic, () => {
                logic.actions.setExpandedTaskId(null)
            }).toMatchValues({
                expandedTaskId: null,
            })
        })

        it('should switch between different expanded tasks', () => {
            const firstTaskId = ActivationTask.IngestFirstEvent
            const secondTaskId = ActivationTask.InviteTeamMember

            expectLogic(logic, () => {
                logic.actions.setExpandedTaskId(firstTaskId)
            }).toMatchValues({
                expandedTaskId: firstTaskId,
            })

            expectLogic(logic, () => {
                logic.actions.setExpandedTaskId(secondTaskId)
            }).toMatchValues({
                expandedTaskId: secondTaskId,
            })
        })
    })
})
