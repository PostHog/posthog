import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic, partial } from 'kea-test-utils'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { NEW_COHORT, NEW_CRITERIA_GROUP } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { urls } from 'scenes/urls'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { mockCohort } from '~/test/mocks'
import {
    AnyCohortCriteriaType,
    BehavioralEventType,
    FilterLogicalOperator,
    InsightShortId,
    PropertyDefinitionState,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    PropertyType,
} from '~/types'

import { CohortCsvUploadModal } from './CohortCsvUploadModal'
import { CohortEdit } from './CohortEdit'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 1000, width: 400 }),
}))

describe('cohortEditLogic', () => {
    let logic: ReturnType<typeof cohortEditLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': toPaginatedResponse([mockCohort]),
                '/api/projects/:team_id/cohorts/:id/': mockCohort,
            },
            post: {
                '/api/projects/:team_id/cohorts/': mockCohort,
                '/api/projects/:team_id/cohorts/:id/': mockCohort,
            },
            patch: {
                '/api/projects/:team_id/cohorts/:id/': mockCohort,
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

    describe('CSV upload modal', () => {
        afterEach(() => {
            cleanup()
        })

        it('clears the chosen CSV on close and on cancel', async () => {
            logic = cohortEditLogic({ id: 10 })
            render(<CohortCsvUploadModal id={10} />)

            // Let the mount-time fetch land first, or its response would replace the state set below.
            await waitFor(() => expect(logic.values.cohort.id).toEqual(mockCohort.id))

            act(() => {
                logic.actions.setCohort({
                    ...NEW_COHORT,
                    id: 10,
                    name: 'Saved cohort',
                    is_static: true,
                    csv: new File(['person@example.com'], 'people.csv', { type: 'text/csv' }),
                })
                logic.actions.setCsvUploadModalOpen(true)
            })

            const closeButton = document.querySelector('.LemonModal__close button') as HTMLElement
            await userEvent.click(closeButton)
            expect(logic.values.cohort.csv).toBeUndefined()
            expect(logic.values.csvUploadModalOpen).toBe(false)

            act(() => {
                logic.actions.setCohortValue('csv', new File(['a@b.com'], 'people.csv', { type: 'text/csv' }))
                logic.actions.setCsvUploadModalOpen(true)
            })
            const cancelButton = document.querySelector('[data-attr="cohort-upload-csv-modal-cancel"]') as HTMLElement
            await userEvent.click(cancelButton)
            expect(logic.values.cohort.csv).toBeUndefined()
            expect(logic.values.csvUploadModalOpen).toBe(false)
        })

        it('shows the size limit and disables Upload for an oversized CSV', async () => {
            logic = cohortEditLogic({ id: 10 })
            render(<CohortCsvUploadModal id={10} />)

            // Let the mount-time fetch land first, or its response would replace the state set below.
            await waitFor(() => expect(logic.values.cohort.id).toEqual(mockCohort.id))

            const csv = new File(['person@example.com'], 'people.csv', { type: 'text/csv' })
            Object.defineProperty(csv, 'size', { value: logic.values.csvMaxBytes + 1 })

            act(() => {
                logic.actions.setCohort({
                    ...NEW_COHORT,
                    id: 10,
                    name: 'Saved cohort',
                    is_static: true,
                    csv,
                })
                logic.actions.setCsvUploadModalOpen(true)
            })

            expect(await screen.findByText(/larger than the limit/i)).toBeVisible()
            const uploadButton = document.querySelector(
                '[data-attr="cohort-upload-csv-modal-save"]'
            ) as HTMLButtonElement
            expect(uploadButton).toHaveAttribute('aria-disabled', 'true')
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

            await new Promise((resolve) => requestAnimationFrame(resolve))

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

        it('shows in progress state when pending_version is set but is_calculating is false', async () => {
            const cohortId = 1

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
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

            render(<CohortEdit id={cohortId} />)

            const inProgressElements = await screen.findAllByText('In progress...')
            expect(inProgressElements.length).toBeGreaterThan(0)
            const queueingElements = screen.getAllByText(
                "We're queuing the calculation. It should be ready in a few minutes."
            )
            expect(queueingElements.length).toBeGreaterThan(0)
        })

        it('shows in progress state when both pending_version and is_calculating are true', async () => {
            const cohortId = 1

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
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

            render(<CohortEdit id={cohortId} />)

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
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
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

            render(<CohortEdit id={cohortId} />)

            await screen.findByText(
                "We're queuing a recalculation. The table below shows results from the previous calculation."
            )
            const inProgressElements = screen.getAllByText('In progress...')
            expect(inProgressElements.length).toBeGreaterThan(0)
        })

        it('hides loading state when calculation is complete', async () => {
            const cohortId = 1

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
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

            render(<CohortEdit id={cohortId} />)

            // Wait a bit for component to render then verify no loading states
            await new Promise((resolve) => setTimeout(resolve, 100))
            expect(screen.queryAllByText('In progress...')).toHaveLength(0)
        })

        it('shows retry button and contact support link when calculation fails', async () => {
            const cohortId = 2

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        // A failed calculation leaves pending_version ahead of version, since version
                        // only advances on success. The error banner must still win over "pending".
                        version: 1,
                        pending_version: 2,
                        is_calculating: false,
                        errors_calculating: 1,
                        last_calculation: '2024-01-01T00:00:00Z',
                        last_error_message: 'Query execution timed out',
                    },
                },
                patch: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        version: 1,
                        pending_version: 2,
                        is_calculating: true,
                        errors_calculating: 0,
                        last_calculation: '2024-01-01T00:00:00Z',
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            // Verify error message is shown
            await screen.findByText(/Calculation failed:/)
            expect(screen.getByText(/Query execution timed out/)).toBeInTheDocument()

            // Verify Retry button is shown as the primary action in the error banner
            // LemonBanner renders action buttons - find the one with "Retry" text
            const retryButtons = screen.getAllByText('Retry')
            expect(retryButtons.length).toBeGreaterThan(0)
            const retryButton = retryButtons[0]

            // Verify contact support link is shown as secondary option
            expect(screen.getByText('contact support')).toBeInTheDocument()

            // Get the logic instance and verify clicking retry triggers submitCohort
            logic = cohortEditLogic({ id: cohortId })
            logic.mount()

            await expectLogic(logic, async () => {
                await userEvent.click(retryButton)
            }).toDispatchActions(['submitCohort'])
        })

        it('shows the error banner, not a pending state, when a stuck calculation has failed', async () => {
            const cohortId = 3

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        // pending_version stuck ahead of version because every calculation failed
                        version: 1,
                        pending_version: 5,
                        is_calculating: false,
                        errors_calculating: 3,
                        last_calculation: '2024-01-01T00:00:00Z',
                        last_error_message: 'Invalid regular expression',
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            await screen.findByText(/Calculation failed:/)
            expect(screen.getByText(/Invalid regular expression/)).toBeInTheDocument()
            // The pending/calculating messaging must not be shown for a failed cohort
            expect(screen.queryAllByText('In progress...')).toHaveLength(0)
            expect(
                screen.queryByText(
                    "We're queuing a recalculation. The table below shows results from the previous calculation."
                )
            ).not.toBeInTheDocument()
        })

        it('shows calculating, not the error banner, while a retry is in flight after a prior failure', async () => {
            const cohortId = 4

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        // A retry is in flight (is_calculating) even though prior attempts errored,
                        // so the calculating banner must win over the failure banner.
                        version: 1,
                        pending_version: 2,
                        is_calculating: true,
                        errors_calculating: 1,
                        last_calculation: '2024-01-01T00:00:00Z',
                        last_error_message: 'Query execution timed out',
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            expect(await screen.findAllByText('In progress...')).not.toHaveLength(0)
            expect(screen.queryByText(/Calculation failed:/)).not.toBeInTheDocument()
        })

        it('shows the failure banner without a retry for a static cohort whose population failed', async () => {
            const cohortId = 7

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        // A static cohort that never populated reports count 0, so the only signal
                        // that the population failed is this banner.
                        is_static: true,
                        filters: { properties: {} },
                        query: { kind: 'HogQLQuery', query: 'SELECT person_id FROM events' },
                        version: null,
                        pending_version: null,
                        is_calculating: false,
                        errors_calculating: 1,
                        last_calculation: null,
                        last_error_message: 'Cohort calculation was terminated for reading too much data.',
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            await screen.findByText(/Calculation failed:/)
            expect(screen.getByText(/reading too much data/)).toBeInTheDocument()
            expect(screen.getByText('contact support')).toBeInTheDocument()
            // The edit form does not resend the source query, so a Retry would not repopulate.
            expect(screen.queryByText('Retry')).not.toBeInTheDocument()
        })

        // Pins the selector contract the fix changed, including the errors_calculating=0 and
        // version=null boundaries the DOM tests above don't exercise.
        it.each([
            // stuck behind because every attempt failed: failed, not pending
            {
                version: 1,
                pending_version: 5,
                is_calculating: false,
                errors_calculating: 3,
                isPending: false,
                isCalcOrPending: false,
            },
            // retry in flight after a prior failure: is_calculating wins
            {
                version: 1,
                pending_version: 2,
                is_calculating: true,
                errors_calculating: 1,
                isPending: false,
                isCalcOrPending: true,
            },
            // genuine pending, never errored
            {
                version: 1,
                pending_version: 2,
                is_calculating: false,
                errors_calculating: 0,
                isPending: true,
                isCalcOrPending: true,
            },
            // never calculated and never errored: pending
            {
                version: null,
                pending_version: 1,
                is_calculating: false,
                errors_calculating: 0,
                isPending: true,
                isCalcOrPending: true,
            },
            // never calculated but already failing: failed, not pending
            {
                version: null,
                pending_version: 1,
                is_calculating: false,
                errors_calculating: 2,
                isPending: false,
                isCalcOrPending: false,
            },
        ])(
            'isPendingCalculation=$isPending / isCalculatingOrPending=$isCalcOrPending for %o',
            async ({ version, pending_version, is_calculating, errors_calculating, isPending, isCalcOrPending }) => {
                logic = cohortEditLogic({ id: 1 })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.setCohort({
                        ...mockCohort,
                        id: 1,
                        version,
                        pending_version,
                        is_calculating,
                        errors_calculating,
                    })
                }).toMatchValues({
                    isPendingCalculation: isPending,
                    isCalculatingOrPending: isCalcOrPending,
                })
            }
        )
    })

    describe('calculation history action', () => {
        afterEach(() => {
            cleanup()
        })

        // ScenePanel portals its actions into the host element the app layout registers. A
        // standalone render never creates one, so the panel stays empty without this.
        function renderWithScenePanel(cohortId: number): void {
            const panelHost = document.createElement('div')
            document.body.appendChild(panelHost)
            const layoutLogic = sceneLayoutLogic()
            layoutLogic.mount()
            layoutLogic.actions.registerScenePanelElement(panelHost)
            render(<CohortEdit id={cohortId} />)
        }

        it.each([
            { type: 'static', isStatic: true },
            { type: 'dynamic', isStatic: false },
        ])('offers calculation history for a saved $type cohort', async ({ isStatic }) => {
            const cohortId = 8

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Test Cohort',
                        is_static: isStatic,
                        filters: { properties: { type: 'AND', values: [] } },
                        version: null,
                        pending_version: null,
                        is_calculating: false,
                        errors_calculating: 0,
                        last_calculation: null,
                    },
                },
            })

            renderWithScenePanel(cohortId)

            // The panel fills in behind a one second timer, so the default one second find budget
            // has almost no margin. Waiting on a sibling action also separates a panel that never
            // rendered from one that rendered without this entry.
            await screen.findByText('Build a custom workflow', {}, { timeout: 5000 })

            // An unloaded cohort has a falsy is_static, which satisfies the gate this test exists
            // to catch, so pin that the fixture reached the scene before asserting on it.
            expect(screen.getByText(isStatic ? 'Static' : 'Dynamic')).toBeInTheDocument()

            // Both cohort types record calculation history, so neither may have the tab that lists
            // it gated away.
            expect(screen.getByText('Calculation history')).toBeInTheDocument()
        })
    })

    describe('import warning', () => {
        afterEach(() => {
            cleanup()
        })

        it('stays hidden after an import that matched every ID', async () => {
            const cohortId = 5
            const cohortName = 'Clean import cohort'
            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        ...mockCohort,
                        id: cohortId,
                        name: cohortName,
                        is_static: true,
                        last_import_total_count: 5,
                        last_import_unmatched_count: 0,
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            await screen.findAllByText(cohortName)
            expect(screen.queryByText("Some IDs in the last import didn't match a person")).not.toBeInTheDocument()
        })

        it('shows the unmatched and total ID counts after a partial import', async () => {
            const cohortId = 6
            const cohortName = 'Partial import cohort'
            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        ...mockCohort,
                        id: cohortId,
                        name: cohortName,
                        is_static: true,
                        last_import_total_count: 7,
                        last_import_unmatched_count: 2,
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            await screen.findAllByText(cohortName)
            const heading = screen.getByText("Some IDs in the last import didn't match a person")
            expect(heading).toBeInTheDocument()
            expect(heading.closest('[aria-live="polite"]')).toBeInTheDocument()
            expect(screen.getByText(/2 of 7 IDs weren't added to this cohort/)).toBeInTheDocument()
        })
    })

    describe('persons list footer', () => {
        afterEach(() => {
            cleanup()
        })

        it.each([
            { count: 2455, expectedFooter: 'Showing 2 of 2,455 entries' },
            { count: 2, expectedFooter: 'Showing all 2 entries' },
            { count: 1, expectedFooter: 'Showing all 2 entries' },
        ])('shows "$expectedFooter" when the cohort count is $count', async ({ count, expectedFooter }) => {
            const cohortId = 7
            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        ...mockCohort,
                        id: cohortId,
                        is_static: false,
                        is_calculating: false,
                        count,
                        version: 1,
                        pending_version: 1,
                        last_calculation: '2024-01-01T00:00:00Z',
                    },
                },
                post: {
                    '/api/environments/:team_id/query/:query_kind/': {
                        columns: ['id'],
                        types: ['UUID'],
                        results: [['person-a'], ['person-b']],
                        hasMore: false,
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            expect(await screen.findByText(expectedFooter)).toBeInTheDocument()
        })
    })

    describe('add users controls on an existing people cohort', () => {
        afterEach(() => {
            cleanup()
        })

        it.each([
            { count: 0, showsInlineUpload: true },
            { count: 3, showsInlineUpload: false },
        ])('with $count people shows inline upload: $showsInlineUpload', async ({ count, showsInlineUpload }) => {
            const cohortId = 20 + count
            const cohortName = `People cohort ${count}`
            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        ...mockCohort,
                        id: cohortId,
                        name: cohortName,
                        is_static: true,
                        filters: { properties: { type: 'OR', values: [] } },
                        count,
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            await screen.findAllByText(cohortName)
            const dropzone = screen.queryByText('Drag a file here or click to browse for a file')
            const addUsersMenu = document.querySelector('[data-attr="cohort-add-users-menu"]')
            if (showsInlineUpload) {
                expect(dropzone).toBeInTheDocument()
                expect(addUsersMenu).not.toBeInTheDocument()
            } else {
                expect(dropzone).not.toBeInTheDocument()
                expect(addUsersMenu).toBeInTheDocument()
            }
        })
    })

    describe('used-in summary', () => {
        afterEach(() => {
            cleanup()
        })

        const cohortId = 8
        const cohortName = 'Referenced cohort'
        // 42 insights behind a 2-item page, and a cohorts block nothing references.
        const usedInMocks = {
            get: {
                [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                    ...mockCohort,
                    id: cohortId,
                    name: cohortName,
                },
                [`/api/projects/:team_id/cohorts/${cohortId}/used_in/`]: {
                    feature_flags: {
                        results: [{ id: 7, key: 'my-flag', name: 'My flag' }],
                        total: 1,
                        has_more: false,
                    },
                    insights: {
                        results: [
                            { id: 1, short_id: 'abc123', name: 'Weekly signups' },
                            { id: 2, short_id: 'def456', name: 'Activation funnel' },
                        ],
                        total: 42,
                        has_more: true,
                    },
                    cohorts: { results: [], total: 0, has_more: false },
                    workflows: { results: [], total: 0, hidden: 0, has_more: false },
                },
            },
        }

        it('counts every use from the total and leaves the list collapsed', async () => {
            useMocks(usedInMocks)

            render(<CohortEdit id={cohortId} />)

            // Anchored: 42 rather than the 2 results the page carried, and no trailing mention of
            // the cohorts block, which nothing references.
            expect(await screen.findByTestId('cohort-used-in-toggle')).toHaveTextContent(
                /^Used in 1 feature flag and 42 insights$/
            )
            expect(screen.queryByText('Weekly signups')).not.toBeInTheDocument()
        })

        it('reveals the grouped links and the truncation note once expanded', async () => {
            useMocks(usedInMocks)

            render(<CohortEdit id={cohortId} />)

            await userEvent.click(await screen.findByTestId('cohort-used-in-toggle'))

            // The rendered href carries the project prefix these helpers leave off.
            expect(screen.getByText('My flag').closest('a')).toHaveAttribute(
                'href',
                expect.stringContaining(urls.featureFlag(7))
            )
            expect(screen.getByText('Weekly signups').closest('a')).toHaveAttribute(
                'href',
                expect.stringContaining(urls.insightView('abc123' as InsightShortId))
            )
            expect(screen.getByText(/2 of 42 shown/)).toBeInTheDocument()
        })
    })

    describe('manual person selection on a new static cohort', () => {
        afterEach(() => {
            cleanup()
        })

        it('keeps the selected people removable while the person search fails', async () => {
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:query_kind/': () => [500, { detail: 'Query failed to execute' }],
                },
            })
            logic = cohortEditLogic({ id: 'new' })
            logic.mount()
            logic.actions.setCohort({ ...NEW_COHORT, is_static: true })
            logic.actions.addPersonToCreateStaticCohort('person-1', 'Jane Doe')
            logic.actions.addPersonToCreateStaticCohort('person-2', 'John Smith')

            render(<CohortEdit id="new" />)

            expect(await screen.findByTestId('insight-empty-state')).toBeInTheDocument()
            const selected = screen.getByTestId('cohort-selected-persons')
            expect(selected).toHaveTextContent('Selected people (2)')

            await userEvent.click(within(within(selected).getByText('Jane Doe').parentElement!).getByRole('button'))

            expect(selected).toHaveTextContent('Selected people (1)')
            expect(within(selected).queryByText('Jane Doe')).not.toBeInTheDocument()
            expect(within(selected).getByText('John Smith')).toBeInTheDocument()
        })
    })

    describe('criteria row type switching', () => {
        afterEach(() => {
            cleanup()
        })

        const q = (selector: string): HTMLElement => {
            const el = document.querySelector(selector)
            if (!el) {
                throw new Error(`not found: ${selector}`)
            }
            return el as HTMLElement
        }

        // mockCohort's single criterion is negated ("Did not complete event", stored as
        // {value: performed_event, negation: true}). Negated criteria store the positive enum
        // plus a negation flag, so a type pick that doesn't reset negation used to leave rows
        // permanently stuck on the negated variant (e.g. "Do not have the property").
        test.each([
            {
                pick: 'cohort-personPropertyBehavioral-have_property-type',
                expectedLabel: 'Have the property',
                expectedCriteria: {
                    type: BehavioralFilterKey.Person,
                    value: BehavioralEventType.HaveProperty,
                    negation: false,
                },
            },
            {
                pick: 'cohort-eventBehavioral-performed_event-type',
                expectedLabel: 'Completed event',
                expectedCriteria: {
                    type: BehavioralFilterKey.Behavioral,
                    value: BehavioralEventType.PerformEvent,
                    negation: false,
                },
            },
            {
                pick: 'cohort-personPropertyBehavioral-not_have_property-type',
                expectedLabel: 'Do not have the property',
                expectedCriteria: {
                    type: BehavioralFilterKey.Person,
                    value: BehavioralEventType.HaveProperty,
                    negation: true,
                },
            },
        ])(
            'switching a negated row via $pick lands on $expectedLabel',
            async ({ pick, expectedLabel, expectedCriteria }) => {
                render(<CohortEdit id={1} />)

                await waitFor(() => {
                    expect(q('[data-attr="cohort-selector-field-value"]')).toHaveTextContent('Did not complete event')
                })

                await userEvent.click(q('[data-attr="cohort-selector-field-value"]'))
                await waitFor(() => {
                    expect(q(`[data-attr="${pick}"]`)).toBeInTheDocument()
                })
                await userEvent.click(q(`[data-attr="${pick}"]`))

                logic = cohortEditLogic({ id: 1 })
                await waitFor(() => {
                    const group = logic.values.cohort.filters.properties.values[0] as {
                        values: AnyCohortCriteriaType[]
                    }
                    expect(group.values[0]).toEqual(expect.objectContaining(expectedCriteria))
                })
                expect(q('[data-attr="cohort-selector-field-value"]')).toHaveTextContent(expectedLabel)
            }
        )
    })

    describe('prefilling a recent person filter', () => {
        const recordPersonRecent = (
            recentFilters: ReturnType<typeof recentTaxonomicFiltersLogic.build>,
            key: string,
            operator: PropertyOperator,
            value: PropertyFilterValue
        ): void => {
            recentFilters.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.PersonProperties,
                groupName: 'Person properties',
                value: key,
                item: { name: key },
                propertyFilter: { type: PropertyFilterType.Person, key, operator, value },
            })
        }

        const suggestedRows = (): HTMLElement[] =>
            Array.from(document.querySelectorAll<HTMLElement>('[data-attr^="prop-filter-suggested_filters-"]'))
        const suggestedText = (): string =>
            suggestedRows()
                .map((row) => row.textContent ?? '')
                .join('||')

        afterEach(() => {
            cleanup()
        })

        it.each([
            ['$browser', PropertyOperator.IContains, 'Chrome', 'Chrome', 'Chrome', 'contains'],
            ['$email', PropertyOperator.IsSet, PropertyOperator.IsSet, 'is set', undefined, 'is set'],
        ])(
            'hides unsupported recents and prefills %s',
            async (key, operator, recordedValue, rowText, expectedValue, expectedOperatorLabel) => {
                const definitions = propertyDefinitionsModel.build()
                definitions.mount()
                definitions.actions.updatePropertyDefinitions({
                    'person/$browser': { id: '$browser', name: '$browser', property_type: PropertyType.String },
                    'person/$email': { id: '$email', name: '$email', property_type: PropertyType.String },
                    'person/$os': { id: '$os', name: '$os', property_type: PropertyType.String },
                    'person/birth_date': PropertyDefinitionState.Loading,
                })
                const recentFilters = recentTaxonomicFiltersLogic.build()
                recentFilters.mount()
                recentFilters.actions.clearRecentFilters()
                recordPersonRecent(recentFilters, 'birth_date', PropertyOperator.IsDateBefore, '2000-01-01')
                recordPersonRecent(recentFilters, key, operator, recordedValue)
                recordPersonRecent(recentFilters, '$os', PropertyOperator.NotIn, ['Mac'])
                logic = cohortEditLogic({ id: 'new' })
                logic.mount()
                logic.actions.setCohort({
                    ...NEW_COHORT,
                    filters: {
                        properties: {
                            ...NEW_COHORT.filters.properties,
                            values: [
                                {
                                    ...NEW_CRITERIA_GROUP,
                                    values: [
                                        {
                                            type: BehavioralFilterKey.Person,
                                            value: BehavioralEventType.HaveProperty,
                                            event_type: TaxonomicFilterGroupType.PersonProperties,
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })

                render(<CohortEdit id="new" />)
                await userEvent.click(await screen.findByText('Choose person property'))
                await waitFor(() => expect(suggestedText()).toContain(rowText))
                expect(suggestedText()).not.toMatch(/Mac|birth_date/)

                await act(async () => {
                    definitions.actions.updatePropertyDefinitions({
                        'person/birth_date': {
                            id: 'birth_date',
                            name: 'birth_date',
                            property_type: PropertyType.DateTime,
                        },
                    })
                })
                await waitFor(() => expect(suggestedText()).toContain('birth_date'))

                await userEvent.click(suggestedRows().find((row) => row.textContent?.includes(rowText))!)

                await waitFor(() => {
                    const group = logic.values.cohort.filters.properties.values[0] as {
                        values: AnyCohortCriteriaType[]
                    }
                    expect(group.values[0]).toEqual(
                        expect.objectContaining({ key, operator, value_property: expectedValue })
                    )
                    expect(document.querySelector('[data-attr="cohort-selector-field-operator"]')).toHaveTextContent(
                        expectedOperatorLabel
                    )
                })
                recentFilters.unmount()
                definitions.unmount()
            }
        )

        it.each([
            {
                key: '$browser',
                propertyType: PropertyType.String,
                operator: PropertyOperator.StartsWith,
                value: 'Chr',
                label: 'starts with',
            },
            {
                key: '$browser',
                propertyType: PropertyType.String,
                operator: PropertyOperator.NotStartsWith,
                value: 'Chr',
                label: 'does not start with',
            },
            {
                key: '$browser',
                propertyType: PropertyType.String,
                operator: PropertyOperator.EndsWith,
                value: 'ome',
                label: 'ends with',
            },
            {
                key: '$browser',
                propertyType: PropertyType.String,
                operator: PropertyOperator.NotEndsWith,
                value: 'ome',
                label: 'does not end with',
            },
            {
                key: '$app_version',
                propertyType: PropertyType.String,
                operator: PropertyOperator.SemverGte,
                value: '1.2.3',
                label: 'greater than or equal (semver)',
            },
            {
                key: 'birth_date',
                propertyType: PropertyType.DateTime,
                operator: PropertyOperator.IsSet,
                value: null,
                label: 'is set',
            },
            {
                key: 'birth_date',
                propertyType: PropertyType.DateTime,
                operator: PropertyOperator.IsNotSet,
                value: null,
                label: 'is not set',
            },
        ])(
            'prefills a recent person filter with $operator during cohort creation',
            async ({ key, propertyType, operator, value, label }) => {
                const definitions = propertyDefinitionsModel.build()
                definitions.mount()
                definitions.actions.updatePropertyDefinitions({
                    [`person/${key}`]: {
                        id: key,
                        name: key,
                        property_type: propertyType,
                    },
                })
                const recentFilters = recentTaxonomicFiltersLogic.build()
                recentFilters.mount()
                recentFilters.actions.clearRecentFilters()
                recordPersonRecent(recentFilters, key, operator, value)
                logic = cohortEditLogic({ id: 'new' })
                logic.mount()
                logic.actions.setCohort({
                    ...NEW_COHORT,
                    filters: {
                        properties: {
                            ...NEW_COHORT.filters.properties,
                            values: [
                                {
                                    ...NEW_CRITERIA_GROUP,
                                    values: [
                                        {
                                            type: BehavioralFilterKey.Person,
                                            value: BehavioralEventType.HaveProperty,
                                            event_type: TaxonomicFilterGroupType.PersonProperties,
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })

                render(<CohortEdit id="new" />)
                await userEvent.click(await screen.findByText('Choose person property'))
                await userEvent.click(await screen.findByTestId('prop-filter-suggested_filters-1'))

                await waitFor(() => {
                    const group = logic.values.cohort.filters.properties.values[0] as {
                        values: AnyCohortCriteriaType[]
                    }
                    expect(group.values[0]).toEqual(
                        expect.objectContaining({
                            key,
                            operator,
                            value_property: value ?? undefined,
                        })
                    )
                    expect(document.querySelector('[data-attr="cohort-selector-field-operator"]')).toHaveTextContent(
                        label
                    )
                    if (value) {
                        expect(screen.getByText(value)).toBeInTheDocument()
                    }
                })
                recentFilters.unmount()
                definitions.unmount()
            }
        )
    })

    describe('type tag on existing cohorts', () => {
        afterEach(() => {
            cleanup()
        })

        it('shows the type as a tag next to the title instead of body rows', async () => {
            const cohortId = 10

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Static Cohort',
                        is_static: true,
                        // Non-empty filter values so `inferStaticCohortMode` resolves to 'criteria' —
                        // an empty `values` array is read as the 'people' (upload/manual) mode instead.
                        filters: mockCohort.filters,
                        version: 1,
                        pending_version: 1,
                        is_calculating: false,
                        last_calculation: '2024-01-01T00:00:00Z',
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            // The type is a tag in the title row; the populate-from detail lives in its tooltip.
            const typeTag = (await screen.findByText('Static')).closest('[data-attr="cohort-type-tag"]')
            expect(typeTag).toBeInTheDocument()

            // The old read-only body rows are gone, so the persons table is not pushed down.
            expect(document.querySelector('[data-attr="cohort-type"]')).not.toBeInTheDocument()
            expect(document.querySelector('[data-attr="static-cohort-mode"]')).not.toBeInTheDocument()
        })
    })

    describe('criteria with unmapped behavioral value', () => {
        afterEach(() => {
            cleanup()
        })

        // Stored criteria can carry a behavioral value with no ROWS entry. Values that instead
        // resolve to an Object.prototype member are covered against getRowShape in cohortUtils.test,
        // since this scene render is the most expensive place to assert the same lookup.
        it('renders an empty, recoverable criteria row for an unmapped value', async () => {
            const cohortId = 11

            useMocks({
                get: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: {
                        id: cohortId,
                        name: 'Unmapped Criteria Cohort',
                        is_static: false,
                        filters: {
                            properties: {
                                id: '1',
                                type: FilterLogicalOperator.Or,
                                values: [
                                    {
                                        id: '2',
                                        type: FilterLogicalOperator.Or,
                                        values: [
                                            {
                                                type: BehavioralFilterKey.Behavioral,
                                                value: 'legacy_unknown_value',
                                                key: '$pageview',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                        version: 1,
                        pending_version: 1,
                        is_calculating: false,
                        last_calculation: '2024-01-01T00:00:00Z',
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)

            // The name only gates on the cohort having loaded; a throw in the row builder has no
            // error boundary between here and the test, so it fails the render outright.
            expect(await screen.findByText('Unmapped Criteria Cohort')).toBeInTheDocument()
            expect(document.querySelector('.CohortCriteriaRow')).toBeInTheDocument()
            expect(screen.getByText('Choose criterion')).toBeInTheDocument()
            // Counting fields is what catches a revert to the PerformEvent fallback: the stored
            // key would label the event picker rather than leave its placeholder visible, so the
            // placeholder assertion above would still pass.
            expect(document.querySelectorAll('.CohortCriteriaRow__Criteria__Field')).toHaveLength(1)
            expect(document.querySelector('.CohortCriteriaRow__Criteria__arrow')).not.toBeInTheDocument()
            expect(screen.getByText("This criterion isn't valid. Choose a new one to replace it.")).toBeInTheDocument()
        })
    })
})
