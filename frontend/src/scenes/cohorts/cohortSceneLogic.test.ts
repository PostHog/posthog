import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'
import { CohortType } from '~/types'

import { cohortSceneLogic } from './cohortSceneLogic'

describe('cohortSceneLogic', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/cohorts/': { count: 0, results: [] } } })
        initKeaTests()
        cohortsModel.mount()
    })

    it('gives the loaded cohort as a People recent', () => {
        cohortsModel.actions.updateCohort({ id: 5, name: 'Churned' } as CohortType)
        const logic = cohortSceneLogic({ id: 5 })
        logic.mount()

        expect(logic.values.todayPeopleRecent).toEqual({ type: 'cohort', name: 'Churned', href: urls.cohort(5) })
    })

    it('gives no recent for a new cohort', () => {
        const logic = cohortSceneLogic({ id: 'new' })
        logic.mount()

        expect(logic.values.todayPeopleRecent).toBeNull()
    })
})
