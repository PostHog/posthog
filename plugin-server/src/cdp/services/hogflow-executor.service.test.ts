import { HogFlow } from '../../schema/hogflow'
import { createExampleHogFlowInvocation } from '../_tests/fixtures-hogflows'
import { HogFlowExecutorService } from './hogflow-executor.service'

describe('HogFlowExecutorService', () => {
    let service: HogFlowExecutorService

    beforeEach(() => {
        service = new HogFlowExecutorService({} as any)
    })

    describe('execute', () => {
        it('should handle archived flow with trigger stop_type', () => {
            const hogFlow: HogFlow = {
                id: 'test-flow',
                team_id: 1,
                version: 1,
                name: 'Test Flow',
                status: 'archived',
                stop_type: 'trigger',
                trigger: { type: 'event', filters: [] },
                edges: [],
                actions: [],
                exit_condition: 'exit_only_at_end',
            }

            const invocation = createExampleHogFlowInvocation(hogFlow)
            const result = service.execute(invocation)

            expect(result.finished).toBe(true)
            expect(result.logs).toHaveLength(1)
            expect(result.logs[0].message).toBe('Flow archived: new events will not trigger this flow')
        })

        it('should handle archived flow with all stop_type', () => {
            const hogFlow: HogFlow = {
                id: 'test-flow',
                team_id: 1,
                version: 1,
                name: 'Test Flow',
                status: 'archived',
                stop_type: 'all',
                trigger: { type: 'event', filters: [] },
                edges: [],
                actions: [],
                exit_condition: 'exit_only_at_end',
            }

            const invocation = createExampleHogFlowInvocation(hogFlow)
            const result = service.execute(invocation)

            expect(result.finished).toBe(true)
            expect(result.logs).toHaveLength(1)
            expect(result.logs[0].message).toBe('Flow archived: all customer movement is halted')
        })

        it('should continue execution for non-archived flow', () => {
            const hogFlow: HogFlow = {
                id: 'test-flow',
                team_id: 1,
                version: 1,
                name: 'Test Flow',
                status: 'active',
                trigger: { type: 'event', filters: [] },
                edges: [],
                actions: [],
                exit_condition: 'exit_only_at_end',
            }

            const invocation = createExampleHogFlowInvocation(hogFlow)
            const result = service.execute(invocation)

            expect(result.finished).toBe(false)
            expect(result.logs).toHaveLength(0)
        })
    })
})
