import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic, partial } from 'kea-test-utils'

import { checkIsPendingCalculation, cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { NEW_COHORT } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { urls } from 'scenes/urls'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockCohort } from '~/test/mocks'
import { AnyCohortCriteriaType, BehavioralEventType, FilterLogicalOperator } from '~/types'

import { CohortEdit } from './CohortEdit'

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

            // The banner must not dead-end: it links to the calculation history so the user can
            // see the actual failure, alongside contacting support.
            const historyLink = screen.getByText('calculation history')
            expect(historyLink.closest('a')?.getAttribute('href')).toContain(urls.cohortCalculationHistory(cohortId))
            expect(screen.getByText('contact support')).toBeInTheDocument()

            // Get the logic instance and verify clicking retry triggers submitCohort
            logic = cohortEditLogic({ id: cohortId })
            logic.mount()

            await expectLogic(logic, async () => {
                await userEvent.click(retryButton)
            }).toDispatchActions(['submitCohort'])
        })

        it('disables the retry button while the recalculation PATCH is in flight', async () => {
            const cohortId = 6
            const failed = {
                id: cohortId,
                name: 'Test Cohort',
                is_static: false,
                filters: { properties: { type: 'AND', values: [] } },
                version: 1,
                pending_version: 2,
                is_calculating: false,
                errors_calculating: 1,
                last_calculation: '2024-01-01T00:00:00Z',
                last_error_message: 'Query execution timed out',
            }
            let releasePatch: () => void = () => {}
            useMocks({
                get: { [`/api/projects/:team_id/cohorts/${cohortId}/`]: failed },
                // Hold the PATCH open so the in-flight window is observable rather than a fast resolve.
                patch: {
                    [`/api/projects/:team_id/cohorts/${cohortId}/`]: async () => {
                        await new Promise<void>((resolve) => {
                            releasePatch = resolve
                        })
                        return { ...failed, is_calculating: true, errors_calculating: 0, pending_version: 3 }
                    },
                },
            })

            render(<CohortEdit id={cohortId} />)
            await screen.findByText(/Calculation failed:/)

            const retryButton = (): HTMLElement | null =>
                document.querySelector('[data-attr="cohort-retry-calculation"]')
            // Enabled once the initial load settles.
            await waitFor(() => expect(retryButton()).toHaveAttribute('aria-disabled', 'false'))

            await userEvent.click(retryButton() as HTMLElement)

            // While the recalculation is queued, the button shows its loading/disabled state so the
            // click doesn't read as inert — the dead-end symptom the PR fixes.
            await waitFor(() => expect(retryButton()).toHaveAttribute('aria-disabled', 'true'))

            // Release the PATCH and let the loader settle so nothing is left in flight; the banner
            // then leaves the error state.
            releasePatch()
            await waitFor(() => expect(screen.queryByText(/Calculation failed:/)).not.toBeInTheDocument())
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

        // A retry the user just queued bumps `pending_version` but leaves `errors_calculating`
        // from the prior failure in place. Without the retry-aware branch the queued attempt reads
        // as "failed", so the error banner reappears the instant a poll finds is_calculating=false
        // — the dead-end this fixes. The branch must still fall back to "failed" once the retry
        // errors again (errors climb past the baseline) or the version catches up, so it can't
        // resurrect the perpetual-pending bug.
        it.each([
            {
                name: 'queued retry, not yet failed again: in progress',
                cohort: { version: 1, pending_version: 2, errors_calculating: 1 },
                retryState: { baselineErrors: 1 },
                expected: true,
            },
            {
                name: 'queued retry that failed again (errors climbed): failed',
                cohort: { version: 1, pending_version: 2, errors_calculating: 2 },
                retryState: { baselineErrors: 1 },
                expected: false,
            },
            {
                name: 'retry queued but version caught up: not pending',
                cohort: { version: 2, pending_version: 2, errors_calculating: 0 },
                retryState: { baselineErrors: 1 },
                expected: false,
            },
        ])('checkIsPendingCalculation — $name', ({ cohort, retryState, expected }) => {
            expect(checkIsPendingCalculation({ ...mockCohort, ...cohort }, retryState)).toBe(expected)
        })

        // The pure-function cases above build `retryState` by hand, so none of them exercise the
        // reducer + loader wiring that produces it. This drives the real submit path: the baseline
        // is snapshotted by setCalculationRetryBaseline *after* setCohort (which clears it), so
        // breaking that dispatch order — or dropping the snapshot — would let the just-queued retry
        // read as "failed" and bring the dead-end back, while every case above still passes.
        it('records the retry baseline through the real save, reading a just-queued retry as in progress', async () => {
            const cohortId = 5
            const failed = {
                id: cohortId,
                name: 'Test Cohort',
                is_static: false,
                filters: { properties: { type: 'AND', values: [] } },
                version: 1,
                pending_version: 2,
                is_calculating: false,
                errors_calculating: 1,
                last_calculation: '2024-01-01T00:00:00Z',
            }
            useMocks({
                get: { [`/api/projects/:team_id/cohorts/${cohortId}/`]: failed },
                // The retry PATCH bumps pending_version but the serializer still returns the prior
                // error count. A fixture that reset it to 0 would snapshot a baseline of 0 and
                // silently defeat the mechanism.
                patch: { [`/api/projects/:team_id/cohorts/${cohortId}/`]: { ...failed, pending_version: 3 } },
            })

            logic = cohortEditLogic({ id: cohortId })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ isPendingCalculation: false })

            await expectLogic(logic, () => logic.actions.submitCohort())
                .toDispatchActions(['saveCohortSuccess'])
                .toMatchValues({
                    calculationRetryState: { baselineErrors: 1 },
                    isPendingCalculation: true,
                })

            logic.unmount()
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

    describe('locked type and populate-from controls on existing cohorts', () => {
        afterEach(() => {
            cleanup()
        })

        it('renders locked controls as a read-only value with an info tooltip, not a dead-click dropdown', async () => {
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

            // The current value is always visible in plain text; the "why can't I change this"
            // explanation lives in an info tooltip instead of being repeated inline.
            const typeContainer = (await screen.findByText('Static')).closest('[data-attr="cohort-type"]')
            const populateFromContainer = screen
                .getByText('Criteria · One-time snapshot')
                .closest('[data-attr="static-cohort-mode"]')
            expect(typeContainer).toBeInTheDocument()
            expect(populateFromContainer).toBeInTheDocument()

            // The locked controls are read-only text, not interactive select buttons (the dead click):
            // a LemonSelect would render the data-attr onto a <button>
            expect(typeContainer?.tagName).not.toBe('BUTTON')
            expect(populateFromContainer?.tagName).not.toBe('BUTTON')
        })
    })

    describe('criteria with unmapped behavioral value', () => {
        afterEach(() => {
            cleanup()
        })

        it('renders the editor instead of crashing when a criterion has a value with no ROWS entry', async () => {
            // Stored criteria can carry a behavioral value with no ROWS entry, which the row builder
            // still has to render. A throw here replaces the whole scene with the error boundary, so
            // finding the cohort name is what proves the criteria row rendered.
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

            expect(await screen.findByText('Unmapped Criteria Cohort')).toBeInTheDocument()
        })
    })
})
