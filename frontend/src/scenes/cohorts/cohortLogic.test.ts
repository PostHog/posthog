import { initKeaTests } from '~/test/init'
import { cohortLogic, CohortLogicProps } from 'scenes/cohorts/cohortLogic'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { mockCohort } from '~/test/mocks'
import { teamLogic } from 'scenes/teamLogic'
import { api } from 'lib/api.mock'
import { cohortsModel } from '~/models/cohortsModel'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'

describe('cohortLogic', () => {
    let logic: ReturnType<typeof cohortLogic.build>

    async function initCohortLogic(props: CohortLogicProps = { id: 'new' }): Promise<void> {
        await expectLogic(teamLogic).toFinishAllListeners()
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'update')
        api.get.mockClear()
        logic = cohortLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/cohorts': [mockCohort],
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
            post: {
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
            patch: {
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
        })
        initKeaTests()
    })

    describe('initial load', () => {
        it('loads existing cohort on mount', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic).toDispatchActions(['fetchCohort'])

            expect(api.get).toBeCalledTimes(1)
        })

        it('loads new cohort on mount', async () => {
            await initCohortLogic({ id: 'new' })
            await expectLogic(logic).toDispatchActions(['setCohort'])

            expect(api.get).toBeCalledTimes(0)
        })

        it('loads new cohort on mount with undefined id', async () => {
            await initCohortLogic({ id: undefined })
            await expectLogic(logic).toDispatchActions(['setCohort'])

            expect(api.get).toBeCalledTimes(0)
        })
    })

    it('delete cohort', async () => {
        await initCohortLogic({ id: 1 })
        await expectLogic(logic, async () => {
            await logic.actions.setCohort(mockCohort)
            await logic.actions.deleteCohort()
        })
            .toFinishAllListeners()
            .toDispatchActions([
                'setCohort',
                'deleteCohort',
                cohortsModel.actionCreators.deleteCohort(mockCohort),
                router.actionCreators.push(urls.cohorts()),
            ])
            .toMatchValues({
                cohort: mockCohort,
            })
        expect(api.update).toBeCalledTimes(1)
    })

    describe('form validation', () => {
        it('save with valid cohort', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort(mockCohort)
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess'])
            expect(api.update).toBeCalledTimes(1)
        })
        it('do not save with invalid name', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    name: '',
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toBeCalledTimes(0)
        })
        it('do not save dynamic cohort with empty groups', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    groups: [],
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toBeCalledTimes(0)
        })
        it('do not save dynamic cohort with malformed events group', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    groups: [
                        {
                            id: '1',
                            matchType: ENTITY_MATCH_TYPE,
                        },
                    ],
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toBeCalledTimes(0)
        })
        it('do not save dynamic cohort with malformed properties group', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    groups: [
                        {
                            id: '1',
                            matchType: PROPERTY_MATCH_TYPE,
                            properties: [],
                        },
                    ],
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toBeCalledTimes(0)
        })
        it('do not save static cohort with empty csv', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    is_static: true,
                    groups: [],
                    csv: undefined,
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toBeCalledTimes(0)
        })
    })
})
