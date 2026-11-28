import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { featureFlagDeleteInProjectsLogic } from './featureFlagDeleteInProjectsLogic'
import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'

const FLAG_ID = 7
const OTHER_PROJECT_ID = MOCK_DEFAULT_TEAM.id + 1
const FLAG = { ...NEW_FLAG, id: FLAG_ID, key: 'test-flag' } as FeatureFlagType

describe('featureFlagDeleteInProjectsLogic', () => {
    let requestBody: Record<string, any> | null

    beforeEach(() => {
        requestBody = null
        useMocks({
            get: {
                '/api/organizations/:organization_id/feature_flags/:feature_flag_key': () => [200, []],
                '/api/projects/:team_id/feature_flags/:id/': () => [200, FLAG],
            },
            post: {
                '/api/organizations/:organization_id/feature_flags/delete_in_projects': async ({ request }) => {
                    requestBody = (await request.json()) as Record<string, any>
                    return [
                        200,
                        {
                            deleted: requestBody!.project_ids
                                .filter((id: number) => id !== OTHER_PROJECT_ID)
                                .map((id: number) => ({ project_id: id, flag_id: FLAG_ID })),
                            failed: requestBody!.project_ids.includes(OTHER_PROJECT_ID)
                                ? [{ project_id: OTHER_PROJECT_ID, error_message: 'Feature flag not found.' }]
                                : [],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess(MOCK_DEFAULT_ORGANIZATION)
    })

    it.each([
        { projectIds: [MOCK_DEFAULT_TEAM.id, OTHER_PROJECT_ID], leavesPage: true },
        { projectIds: [OTHER_PROJECT_ID], leavesPage: false },
    ])(
        'sends the key and projects, and leaves the page on close only when it deleted this flag ($projectIds)',
        async ({ projectIds, leavesPage }) => {
            router.actions.push(urls.featureFlag(FLAG_ID))
            const flagLogic = featureFlagLogic({ id: FLAG_ID })
            flagLogic.mount()
            await expectLogic(flagLogic).toDispatchActions(['loadFeatureFlagSuccess'])
            const logic = featureFlagDeleteInProjectsLogic({ id: FLAG_ID })
            logic.mount()

            await expectLogic(logic, () => logic.actions.deleteInProjects(projectIds))
                .toDispatchActions(['deleteInProjectsSuccess', flagLogic.actionTypes.loadProjectsWithCurrentFlag])
                .toMatchValues({ deleteInProjectsResultVisible: true, currentFlagDeleted: leavesPage })
            expect(requestBody).toEqual({ feature_flag_key: 'test-flag', project_ids: projectIds })

            logic.actions.closeDeleteInProjectsResult()
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(
                leavesPage ? urls.featureFlags() : urls.featureFlag(FLAG_ID)
            )
        }
    )
})
