import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { NotificationProject, notificationProjectsLogic } from './notificationProjectsLogic'

describe('notificationProjectsLogic', () => {
    let logic: ReturnType<typeof notificationProjectsLogic.build>

    const projects: NotificationProject[] = [
        { id: 3, name: 'Zebra', organizationId: 'org-b', organizationName: 'Beta Org' },
        { id: 1, name: 'Apple', organizationId: 'org-a', organizationName: 'Alpha Org' },
        { id: 2, name: 'Mango', organizationId: 'org-a', organizationName: 'Alpha Org' },
    ]

    beforeEach(() => {
        // No current user, so the mount-time subscription doesn't kick off a real load and we can
        // drive the loader state directly for deterministic selector assertions.
        window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
        initKeaTests()
        logic = notificationProjectsLogic()
        logic.mount()
    })

    it('projectsByOrganization: groups projects by organization, sorting both orgs and projects by name', async () => {
        logic.actions.loadProjectsSuccess(projects)

        await expectLogic(logic).toMatchValues({
            projectsByOrganization: [
                {
                    organizationId: 'org-a',
                    organizationName: 'Alpha Org',
                    projects: [projects[1], projects[2]],
                },
                {
                    organizationId: 'org-b',
                    organizationName: 'Beta Org',
                    projects: [projects[0]],
                },
            ],
        })
    })

    it('allProjectIds: returns every project id across organizations', async () => {
        logic.actions.loadProjectsSuccess(projects)

        expect(logic.values.allProjectIds).toEqual([3, 1, 2])
    })
})
