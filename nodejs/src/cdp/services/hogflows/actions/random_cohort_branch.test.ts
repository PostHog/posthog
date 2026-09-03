import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'

import { findActionById, findActionByType } from '../hogflow-utils'
import { getRandomCohort } from './random_cohort_branch'

describe('getRandomCohort', () => {
    let action: Extract<HogFlowAction, { type: 'random_cohort_branch' }>
    let invocation: CyclotronJobInvocationHogFlow

    beforeEach(() => {
        jest.useFakeTimers()
        jest.spyOn(Math, 'random')

        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    random_cohort_branch: {
                        type: 'random_cohort_branch',
                        config: {
                            cohorts: [{ percentage: 30 }, { percentage: 40 }, { percentage: 30 }],
                        },
                    },
                    cohort_a: {
                        type: 'delay',
                        config: { delay_duration: '2h' },
                    },
                    cohort_b: {
                        type: 'delay',
                        config: { delay_duration: '2h' },
                    },
                    cohort_c: {
                        type: 'delay',
                        config: { delay_duration: '2h' },
                    },
                },
                edges: [
                    {
                        from: 'random_cohort_branch',
                        to: 'cohort_a',
                        type: 'branch',
                        index: 0,
                    },
                    {
                        from: 'random_cohort_branch',
                        to: 'cohort_b',
                        type: 'branch',
                        index: 1,
                    },
                    {
                        from: 'random_cohort_branch',
                        to: 'cohort_c',
                        type: 'branch',
                        index: 2,
                    },
                ],
            })
            .build()

        action = findActionByType(hogFlow, 'random_cohort_branch')!
        invocation = createExampleHogFlowInvocation(hogFlow)
    })

    it('should select first cohort when random is in first range', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.2) // 20% - in first cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_a'))
    })

    it('should select second cohort when random is in second range', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.4) // 40% - in second cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_b'))
    })

    it('should select third cohort when random is in third range', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.8) // 80% - in third cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_c'))
    })

    it('should handle edge cases at boundaries', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.3) // Exactly at first boundary
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_a'))
        ;(Math.random as jest.Mock).mockReturnValue(0.7) // Exactly at second boundary
        const result2 = getRandomCohort(invocation, action)
        expect(result2).toEqual(findActionById(invocation.hogFlow, 'cohort_b'))
    })

    it.each([
        ['missing', undefined],
        ['empty', []],
        ['not an array', { percentage: 50 }],
        ['all zero', [{ percentage: 0 }, { percentage: 0 }]],
    ])('should fall through the continue edge when cohorts is %s', (_name, cohorts) => {
        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    broken_branch: {
                        type: 'random_cohort_branch',
                        config: { cohorts: [] },
                    },
                    after: {
                        type: 'delay',
                        config: { delay_duration: '2h' },
                    },
                },
                edges: [
                    {
                        from: 'broken_branch',
                        to: 'after',
                        type: 'continue',
                    },
                ],
            })
            .build()
        const brokenAction = findActionByType(hogFlow, 'random_cohort_branch')!
        ;(brokenAction.config as any).cohorts = cohorts

        const result = getRandomCohort(createExampleHogFlowInvocation(hogFlow), brokenAction)
        expect(result).toEqual(findActionById(hogFlow, 'after'))
    })

    it('should handle single cohort', () => {
        action.config.cohorts = [{ percentage: 100 }]
        ;(Math.random as jest.Mock).mockReturnValue(0.9)
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_a'))
    })

    it('should handle uneven percentages', () => {
        action.config.cohorts = [{ percentage: 25 }, { percentage: 75 }]
        ;(Math.random as jest.Mock).mockReturnValue(0.5) // 50% - in second cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_b'))
    })

    it.each([
        ['first', 0.49, 'cohort_a'],
        ['second', 0.51, 'cohort_b'],
    ])(
        'should keep an even split proportional when percentages dont add up to 100 (%s half)',
        (_name, random, expected) => {
            // Two cohorts at 30% each are a 50/50 split, not 30/30/40-to-the-last-cohort.
            action.config.cohorts = [{ percentage: 30 }, { percentage: 30 }]
            ;(Math.random as jest.Mock).mockReturnValue(random)
            expect(getRandomCohort(invocation, action)).toEqual(findActionById(invocation.hogFlow, expected))
        }
    )

    describe('sticky_assignment', () => {
        const cohortFor = (personId: string, flow = invocation.hogFlow): string =>
            getRandomCohort(
                createExampleHogFlowInvocation(flow, {}, { id: personId }),
                findActionByType(flow, 'random_cohort_branch')!
            ).id

        beforeEach(() => {
            action.config.sticky_assignment = true
        })

        it('assigns the same person the same cohort every time, without consulting the RNG', () => {
            const assignments = new Set(Array.from({ length: 20 }, () => cohortFor('person_a')))

            expect(assignments.size).toBe(1)
            expect(Math.random).not.toHaveBeenCalled()
        })

        it('spreads people across cohorts in line with the configured percentages', () => {
            const counts: Record<string, number> = { cohort_a: 0, cohort_b: 0, cohort_c: 0 }
            const total = 3000
            for (let i = 0; i < total; i++) {
                counts[cohortFor(`person_${i}`)]++
            }

            // Configured 30/40/30. The fixture's flow id is a fresh UUID per run so the salt varies;
            // n is large enough that these bounds hold regardless. They still fail the mistakes that
            // matter: a key ignoring the person id, or a mis-scaled hash, puts everyone in one cohort.
            expect(counts.cohort_a / total).toBeCloseTo(0.3, 1)
            expect(counts.cohort_b / total).toBeCloseTo(0.4, 1)
            expect(counts.cohort_c / total).toBeCloseTo(0.3, 1)
        })

        it('buckets two splits in one workflow independently', () => {
            const twoSplits = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        split_one: {
                            type: 'random_cohort_branch',
                            config: { cohorts: [{ percentage: 50 }, { percentage: 50 }], sticky_assignment: true },
                        },
                        split_two: {
                            type: 'random_cohort_branch',
                            config: { cohorts: [{ percentage: 50 }, { percentage: 50 }], sticky_assignment: true },
                        },
                        one_a: { type: 'delay', config: { delay_duration: '2h' } },
                        one_b: { type: 'delay', config: { delay_duration: '2h' } },
                        two_a: { type: 'delay', config: { delay_duration: '2h' } },
                        two_b: { type: 'delay', config: { delay_duration: '2h' } },
                    },
                    edges: [
                        { from: 'split_one', to: 'one_a', type: 'branch', index: 0 },
                        { from: 'split_one', to: 'one_b', type: 'branch', index: 1 },
                        { from: 'split_two', to: 'two_a', type: 'branch', index: 0 },
                        { from: 'split_two', to: 'two_b', type: 'branch', index: 1 },
                    ],
                })
                .build()

            const branchIndex = (actionId: string, personId: string): number => {
                const splitAction = findActionById(twoSplits, actionId) as typeof action
                const run = createExampleHogFlowInvocation(twoSplits, {}, { id: personId })
                return getRandomCohort(run, splitAction).id.endsWith('_a') ? 0 : 1
            }

            // Without the per-action salt every person lands on the same side of both splits.
            const people = Array.from({ length: 50 }, (_, i) => `person_${i}`)
            const agreements = people.filter((p) => branchIndex('split_one', p) === branchIndex('split_two', p)).length

            expect(agreements).toBeGreaterThan(0)
            expect(agreements).toBeLessThan(people.length)
        })

        it('keeps the bucket keyed by the person id when the person fails to resolve mid-run', () => {
            // 10 people, not 1: with one key pair a regression that keys on the distinct_id instead
            // could still land both runs in the same cohort by hash coincidence.
            for (let i = 0; i < 10; i++) {
                const personUuid = `person_uuid_${i}`
                const resolved = createExampleHogFlowInvocation(invocation.hogFlow, {}, { id: personUuid })
                const unresolved = createExampleHogFlowInvocation(invocation.hogFlow, { personId: personUuid })
                delete unresolved.person

                expect(getRandomCohort(unresolved, action)).toEqual(getRandomCohort(resolved, action))
            }
            expect(Math.random).not.toHaveBeenCalled()
        })

        it('keys on the trigger event distinct id when the run has no person, as accounts audiences do', () => {
            const accountRun = (): CyclotronJobInvocationHogFlow => {
                const run = createExampleHogFlowInvocation(invocation.hogFlow)
                delete run.person
                return run
            }

            const assignments = new Set(Array.from({ length: 20 }, () => getRandomCohort(accountRun(), action).id))

            expect(assignments.size).toBe(1)
            expect(Math.random).not.toHaveBeenCalled()
        })

        it('falls back to random assignment when the run has nothing stable to key on', () => {
            const withoutPerson = createExampleHogFlowInvocation(invocation.hogFlow)
            delete withoutPerson.person
            withoutPerson.state!.event.distinct_id = ''
            ;(Math.random as jest.Mock).mockReturnValue(0.8)

            expect(getRandomCohort(withoutPerson, action)).toEqual(findActionById(invocation.hogFlow, 'cohort_c'))
        })
    })
})
