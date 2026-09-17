import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { tagsModel } from './tagsModel'

describe('tagsModel', () => {
    let logic: ReturnType<typeof tagsModel.build>

    beforeEach(() => {
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        logic = tagsModel.build()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('shows cached tags for the project selected after mounting', () => {
        const nextProject = { ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 }
        logic.actions.setProjectTags(MOCK_DEFAULT_TEAM.id, ['first-project'])
        logic.actions.setProjectTags(nextProject.id, ['second-project'])

        teamLogic.actions.loadCurrentTeamSuccess(nextProject)

        expect(logic.values.tags).toEqual(['second-project'])
    })

    it('keeps refreshed tags when an earlier request finishes afterwards', async () => {
        let resolveInitialRequest: (tags: string[]) => void
        let resolveRefreshRequest: (tags: string[]) => void
        const initialRequest = new Promise<string[]>((resolve) => {
            resolveInitialRequest = resolve
        })
        const refreshRequest = new Promise<string[]>((resolve) => {
            resolveRefreshRequest = resolve
        })
        const listTags = jest
            .spyOn(api.tags, 'list')
            .mockReturnValueOnce(initialRequest)
            .mockReturnValueOnce(refreshRequest)

        logic.actions.loadTagsIfNeeded()
        await Promise.resolve()
        logic.actions.refreshTags()
        await Promise.resolve()

        expect(listTags).toHaveBeenCalledTimes(2)
        const projectId = listTags.mock.calls[0][0]
        if (projectId === undefined) {
            throw new Error('Expected a project ID')
        }

        await expectLogic(logic, () => resolveRefreshRequest!(['refreshed'])).toDispatchActions(['loadTagsSuccess'])
        expect(logic.values.tagsByProject[projectId]).toEqual(['refreshed'])

        resolveInitialRequest!(['stale'])
        await initialRequest
        await Promise.resolve()
        expect(logic.values.tagsByProject[projectId]).toEqual(['refreshed'])
    })
})
