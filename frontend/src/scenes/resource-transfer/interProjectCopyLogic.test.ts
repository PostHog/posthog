import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'
import { TeamBasicType } from '~/types'

import { interProjectCopyLogic } from './interProjectCopyLogic'

describe('interProjectCopyLogic', () => {
    let logic: ReturnType<typeof interProjectCopyLogic.build>

    beforeEach(() => {
        initKeaTests()
        organizationLogic.mount()
        logic = interProjectCopyLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        organizationLogic.unmount()
    })

    function setProjectCount(count: number): void {
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            teams: Array.from({ length: count }, (_, index) => ({ id: index + 1 }) as TeamBasicType),
        })
    }

    // No feature flags are set here on purpose: the transfer API is ungated, so having somewhere to copy to
    // must be the only requirement. A flag gate used to hide the action whenever it failed to resolve.
    it('allows copying when the organization has more than one project', async () => {
        setProjectCount(2)
        await expectLogic(logic).toMatchValues({
            canCopyToProject: true,
            copyToProjectDisabledReason: null,
        })
    })

    it('explains why copying is unavailable when the organization has a single project', async () => {
        setProjectCount(1)
        await expectLogic(logic).toMatchValues({
            canCopyToProject: false,
            copyToProjectDisabledReason: expect.stringContaining('only has one project'),
        })
    })
})
