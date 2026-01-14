import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic, partial } from 'kea-test-utils'

import { NEW_COHORT } from 'scenes/cohorts/CohortFilters/constants'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockCohort } from '~/test/mocks'

import { CohortEdit } from './CohortEdit'

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

    describe('calculation status', () => {
        afterEach(() => {
            cleanup()
        })

        it('shows pending state when pending_version is set but is_calculating is false', async () => {
            const cohortId = 1

            useMocks({
                get: {
                    [`/api/projects/:team/cohorts/${cohortId}`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        version: null,
                        pending_version: 1,
                        is_calculating: false,
                        last_calculation: null,
                    },
                },
            })

            render(<CohortEdit id={cohortId} tabId="test-tab" />)

            const pendingElements = await screen.findAllByText('Pending...')
            expect(pendingElements.length).toBeGreaterThan(0)
            const queueingElements = screen.getAllByText(
                "We're queuing the calculation. It should be ready in a few minutes."
            )
            expect(queueingElements.length).toBeGreaterThan(0)
        })

        it('shows in progress state when both pending_version and is_calculating are true', async () => {
            const cohortId = 1

            useMocks({
                get: {
                    [`/api/projects/:team/cohorts/${cohortId}`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        version: null,
                        pending_version: 1,
                        is_calculating: true,
                        last_calculation: null,
                    },
                },
            })

            render(<CohortEdit id={cohortId} tabId="test-tab" />)

            const inProgressElements = await screen.findAllByText('In progress...')
            expect(inProgressElements.length).toBeGreaterThan(0)
            const calculatingElements = screen.getAllByText(
                "We're calculating the cohort. It should be ready in a few minutes."
            )
            expect(calculatingElements.length).toBeGreaterThan(0)
        })

        it('shows previous data when recalculation is pending', async () => {
            const cohortId = 1

            useMocks({
                get: {
                    [`/api/projects/:team/cohorts/${cohortId}`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        version: 1,
                        pending_version: 2,
                        is_calculating: false,
                        last_calculation: '2024-01-01T00:00:00Z',
                    },
                },
            })

            render(<CohortEdit id={cohortId} tabId="test-tab" />)

            await screen.findByText(
                "We're queuing a recalculation. The table below shows results from the previous calculation."
            )
            const pendingElements = screen.getAllByText('Pending...')
            expect(pendingElements.length).toBeGreaterThan(0)
        })

        it('hides loading state when calculation is complete', async () => {
            const cohortId = 1

            useMocks({
                get: {
                    [`/api/projects/:team/cohorts/${cohortId}`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        version: 1,
                        pending_version: 1,
                        is_calculating: false,
                        last_calculation: '2024-01-01T00:00:00Z',
                    },
                },
            })

            render(<CohortEdit id={cohortId} tabId="test-tab" />)

            // Wait a bit for component to render then verify no loading states
            await new Promise((resolve) => setTimeout(resolve, 100))
            expect(screen.queryAllByText('Pending...')).toHaveLength(0)
            expect(screen.queryAllByText('In progress...')).toHaveLength(0)
        })
    })
})
