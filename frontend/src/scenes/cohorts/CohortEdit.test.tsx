import { expectLogic, partial } from 'kea-test-utils'

import { NEW_COHORT } from 'scenes/cohorts/CohortFilters/constants'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockCohort } from '~/test/mocks'

describe('cohortEditLogic', () => {
    let logic: ReturnType<typeof cohortEditLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/cohorts': [mockCohort],
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
            post: {
                '/api/projects/:team/cohorts/': mockCohort,
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
            patch: {
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
        })
        initKeaTests()
    })

    describe('form validation', () => {
        it('prevents submission when name is empty and shows error', async () => {
            logic = cohortEditLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setCohort({
                    ...NEW_COHORT,
                    id: 'new',
                    name: '',
                })
                logic.actions.submitCohort()
            })
                .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
                .toMatchValues({
                    cohortErrors: partial({
                        name: 'Cohort name cannot be empty',
                        filters: {
                            properties: {
                                values: [
                                    {
                                        values: [
                                            {
                                                event_filters: undefined,
                                                event_type: undefined,
                                                explicit_datetime: undefined,
                                                id: 'Event or action cannot be empty.',
                                                key: 'Event or action cannot be empty.',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    }),
                })
        })

        it('allows submission when name is provided with static cohort and CSV', async () => {
            logic = cohortEditLogic({ id: 'new' })
            logic.mount()

            // Create a mock CSV file
            const mockCsvFile = new File(['user1\nuser2'], 'test.csv', { type: 'text/csv' })

            await expectLogic(logic, () => {
                // Create a static cohort with a CSV file
                logic.actions.setCohort({
                    ...NEW_COHORT,
                    id: 'new',
                    name: 'Valid Cohort Name',
                    is_static: true,
                    csv: mockCsvFile,
                })
                logic.actions.submitCohort()
            })
                .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess'])
                .toMatchValues({
                    cohortErrors: {},
                })
        })
    })

    describe('scroll to error functionality', () => {
        let scrollIntoViewSpy: jest.SpyInstance
        let querySelectorSpy: jest.SpyInstance

        beforeEach(() => {
            scrollIntoViewSpy = jest.fn()
            querySelectorSpy = jest.spyOn(document, 'querySelector')

            const mockElement = {
                scrollIntoView: scrollIntoViewSpy,
            }
            querySelectorSpy.mockReturnValue(mockElement as unknown as Element)
        })

        afterEach(() => {
            scrollIntoViewSpy.mockRestore()
            querySelectorSpy.mockRestore()
        })

        it('scrolls to error element when validation fails', async () => {
            logic = cohortEditLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    id: 'new',
                    name: '',
                })
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])

            await new Promise((resolve) => setTimeout(resolve, 10))

            expect(querySelectorSpy).toHaveBeenCalledWith('.Field--error')
            expect(scrollIntoViewSpy).toHaveBeenCalledWith({
                block: 'center',
                behavior: 'smooth',
            })
        })

        it('falls back to CohortCriteriaRow error selector', async () => {
            logic = cohortEditLogic({ id: 'new' })
            logic.mount()

            querySelectorSpy
                .mockReturnValueOnce(null)
                .mockReturnValueOnce({ scrollIntoView: scrollIntoViewSpy } as unknown as Element)

            await expectLogic(logic, () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    id: 'new',
                    name: '',
                })
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])

            await new Promise((resolve) => requestAnimationFrame(resolve))

            expect(querySelectorSpy).toHaveBeenCalledWith('.Field--error')
            expect(querySelectorSpy).toHaveBeenCalledWith('.CohortCriteriaRow__Criteria--error')
            expect(scrollIntoViewSpy).toHaveBeenCalledWith({
                block: 'center',
                behavior: 'smooth',
            })
        })

        it('does not scroll when no error element is found', async () => {
            logic = cohortEditLogic({ id: 'new' })
            logic.mount()

            querySelectorSpy.mockReturnValue(null)

            await expectLogic(logic, () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    id: 'new',
                    name: '',
                })
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])

            await new Promise((resolve) => setTimeout(resolve, 10))

            expect(scrollIntoViewSpy).not.toHaveBeenCalled()
        })
    })
})
