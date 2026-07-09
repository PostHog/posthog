import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'

import { findActionById, findActionByType } from '../hogflow-utils'
import { ExperimentBranchHandler, calculateHash } from './experiment_branch'

describe('ExperimentBranchHandler', () => {
    // Parity anchor: these vectors are copied from test_calculate_hash in
    // rust/feature-flags/src/flags/flag_matching_utils.rs. If this fails, executor variant
    // assignment has diverged from what the flags service would serve for the same flag key.
    it.each([
        ['some_distinct_id', 0.7270002403585725],
        ['test-identifier', 0.4493881716040236],
        ['example_id', 0.9402003475831224],
        ['example_id2', 0.6292740389966519],
    ])('calculateHash matches the rust implementation for %s', (identifier, expected) => {
        expect(calculateHash('holdout-', identifier, '')).toBe(expected)
    })

    describe('execute', () => {
        let action: Extract<HogFlowAction, { type: 'experiment_branch' }>
        let invocation: CyclotronJobInvocationHogFlow
        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
        const handler = new ExperimentBranchHandler()

        beforeEach(() => {
            const hogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        experiment_branch: {
                            type: 'experiment_branch',
                            config: {
                                feature_flag_key: 'flag-key',
                                variants: [
                                    { key: 'control', percentage: 50 },
                                    { key: 'test', percentage: 50 },
                                ],
                            },
                        },
                        branch_control: { type: 'delay', config: { delay_duration: '2h' } },
                        branch_test: { type: 'delay', config: { delay_duration: '2h' } },
                    },
                    edges: [
                        { from: 'experiment_branch', to: 'branch_control', type: 'branch', index: 0 },
                        { from: 'experiment_branch', to: 'branch_test', type: 'branch', index: 1 },
                    ],
                })
                .build()
            hogFlow.id = 'workflow-id'

            action = findActionByType(hogFlow, 'experiment_branch')!
            invocation = createExampleHogFlowInvocation(hogFlow)
            result = createInvocationResult(invocation)
        })

        const executeFor = (distinctId: string | undefined): ReturnType<ExperimentBranchHandler['execute']> => {
            invocation.person = distinctId
                ? { id: 'person_id', properties: {}, name: 'Test', url: '', distinct_id: distinctId }
                : undefined
            return handler.execute({ invocation, action, result })
        }

        // Expected buckets computed independently (Python sha1, rust float semantics) for
        // 'workflow-flag-key.{distinct_id}variant' with a 50/50 control/test split.
        it.each([
            ['user_1', 'control', 'branch_control'],
            ['user_2', 'test', 'branch_test'],
            ['user_4', 'control', 'branch_control'],
            ['user_5', 'test', 'branch_test'],
        ])('assigns %s deterministically to %s', (distinctId, expectedVariant, expectedActionId) => {
            action.config.feature_flag_key = 'workflow-flag-key'
            const handlerResult = executeFor(distinctId)

            expect(handlerResult.result).toEqual({ variant: expectedVariant })
            expect(handlerResult.nextAction).toEqual(findActionById(invocation.hogFlow, expectedActionId))
            // Sticky: a second pass makes the same choice
            expect(executeFor(distinctId).nextAction?.id).toBe(expectedActionId)
        })

        it('emits an exposure event carrying the variant and workflow context', () => {
            action.config.feature_flag_key = 'workflow-flag-key'
            action.config.experiment_id = 42
            executeFor('user_1')

            expect(result.capturedPostHogEvents).toEqual([
                {
                    team_id: invocation.hogFlow.team_id,
                    event: '$workflows_experiment_exposure',
                    distinct_id: 'user_1',
                    timestamp: expect.any(String),
                    properties: {
                        '$feature/workflow-flag-key': 'control',
                        feature_flag: 'workflow-flag-key',
                        variant: 'control',
                        $workflow_id: 'workflow-id',
                        $workflow_action_id: action.id,
                        $experiment_id: 42,
                    },
                },
            ])
        })

        it('falls back to a flow-and-action-derived hash key when no feature flag key is set', () => {
            action.config.feature_flag_key = undefined
            const handlerResult = executeFor('user_1')

            expect(handlerResult.nextAction).toBeDefined()
            expect(result.capturedPostHogEvents[0].properties.feature_flag).toBe(`workflow-workflow-id-${action.id}`)
        })

        it('routes to the winner without emitting exposure once promoted', () => {
            action.config.winner = 'test'
            const handlerResult = executeFor('user_1') // user_1 would hash to control

            expect(handlerResult.result).toEqual({ variant: 'test', winner_promoted: true })
            expect(handlerResult.nextAction).toEqual(findActionById(invocation.hogFlow, 'branch_test'))
            expect(result.capturedPostHogEvents).toEqual([])
        })

        it('routes to control without exposure when there is no distinct_id', () => {
            invocation.state.event.distinct_id = ''
            const handlerResult = executeFor(undefined)

            expect(handlerResult.result).toEqual({ variant: 'control', exposure_skipped: true })
            expect(handlerResult.nextAction).toEqual(findActionById(invocation.hogFlow, 'branch_control'))
            expect(result.capturedPostHogEvents).toEqual([])
        })
    })
})
