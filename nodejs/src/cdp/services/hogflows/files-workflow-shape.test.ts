import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '~/cdp/_tests/builders/hogflow.builder'
import { HogFlow } from '~/cdp/schema/hogflow'

import { filesWorkflowShape } from './files-workflow-shape'

type Actions = SimpleHogFlowRepresentation['actions']
type Edges = SimpleHogFlowRepresentation['edges']
type Expected = { emailStep: string } | { error: string; step: string | null }

const trigger = { type: 'trigger', config: { type: 'api' } } as const
const email = (
    category: 'transactional' | 'marketing' = 'transactional',
    config: { skip_frequency_cap?: boolean } = {}
) =>
    ({
        type: 'function_email',
        config: { template_id: 'template-email', inputs: {}, message_category_type: category, ...config },
    }) as const
const genericEmailFunction = {
    type: 'function',
    config: { template_id: 'template-email', inputs: {} },
} as const
const delay = { type: 'delay', config: { delay_duration: '1h' } } as const
const branch = { type: 'conditional_branch' as const, config: { conditions: [{ filters: {} }] } }
const exit = { type: 'exit', config: {} } as const
const step = (from: string, to: string) => ({ from, to, type: 'continue' as const })
const namedById = (actions: Actions): Actions =>
    Object.fromEntries(Object.entries(actions).map(([id, action]) => [id, { ...action, name: id }]))
const flowOf = (actions: Actions, edges: Edges, settings: Partial<HogFlow> = {}): HogFlow => ({
    ...new FixtureHogFlowBuilder().withWorkflow({ actions: namedById(actions), edges }).build(),
    ...settings,
})

const longChainAfterEmail = (length: number): { actions: Actions; edges: Edges } => {
    const ids = Array.from({ length }, (_, index) => `after_${index}`)
    return {
        actions: { trigger, email: email(), ...Object.fromEntries(ids.map((id) => [id, delay])) },
        edges: [
            step('trigger', 'email'),
            ...['email', ...ids].slice(0, -1).map((from, index) => step(from, ids[index])),
        ],
    }
}

describe('filesWorkflowShape', () => {
    const chain = longChainAfterEmail(20_000)

    it.each<[string, Actions, Edges, Expected, Partial<HogFlow>?]>([
        [
            'the generated workflow, a trigger, an email step and an exit',
            { trigger, email: email(), exit },
            [step('trigger', 'email'), step('email', 'exit')],
            { emailStep: 'email' },
        ],
        [
            'the generated workflow without its exit',
            { trigger, email: email() },
            [step('trigger', 'email')],
            { emailStep: 'email' },
        ],
        [
            'the generated workflow beside a step the trigger never reaches',
            { trigger, email: email(), exit, later: delay },
            [step('trigger', 'email'), step('email', 'exit'), step('later', 'exit')],
            { emailStep: 'email' },
        ],
        [
            'a generic function step that runs the email template',
            { trigger, send: genericEmailFunction, exit },
            [step('trigger', 'send'), step('send', 'exit')],
            { error: 'workflow_shape_not_supported', step: 'send' },
        ],
        [
            'a delay before the email',
            { trigger, wait: delay, email: email() },
            [step('trigger', 'wait'), step('wait', 'email')],
            { error: 'workflow_shape_not_supported', step: 'wait' },
        ],
        [
            'a delay after the email',
            { trigger, email: email(), wait: delay, exit },
            [step('trigger', 'email'), step('email', 'wait'), step('wait', 'exit')],
            { error: 'workflow_shape_not_supported', step: 'wait' },
        ],
        [
            'a second email',
            { trigger, email: email(), second: email() },
            [step('trigger', 'email'), step('email', 'second')],
            { error: 'workflow_shape_not_supported', step: 'second' },
        ],
        [
            'a branch before the email',
            { trigger, choose: branch, email: email() },
            [step('trigger', 'choose'), { from: 'choose', to: 'email', type: 'branch', index: 0 }],
            { error: 'workflow_shape_not_supported', step: 'choose' },
        ],
        [
            'an email step that loops back to itself',
            { trigger, email: email() },
            [step('trigger', 'email'), step('email', 'email')],
            { error: 'workflow_shape_not_supported', step: 'email' },
        ],
        [
            'a trigger that also leads straight to an exit',
            { trigger, email: email(), done: exit },
            [step('trigger', 'email'), step('trigger', 'done')],
            { error: 'workflow_shape_not_supported', step: 'done' },
        ],
        [
            'no email step',
            { trigger, exit },
            [step('trigger', 'exit')],
            { error: 'workflow_shape_not_supported', step: null },
        ],
        [
            'a marketing email step whose frequency cap can hold it',
            { trigger, email: email('marketing'), exit },
            [step('trigger', 'email'), step('email', 'exit')],
            { error: 'workflow_can_wait', step: 'email' },
        ],
        [
            'a marketing email step that skips the frequency cap, which the team sending cap can still hold',
            { trigger, email: email('marketing', { skip_frequency_cap: true }), exit },
            [step('trigger', 'email'), step('email', 'exit')],
            { error: 'workflow_can_wait', step: 'email' },
        ],
        [
            'the generated workflow under a sending rate limit, which can hold the email',
            { trigger, email: email(), exit },
            [step('trigger', 'email'), step('email', 'exit')],
            { error: 'workflow_can_wait', step: null },
            { email_sending_rate_limit: { count: 100, period: 'hour' } },
        ],
        [
            'the generated workflow with its sending rate limit cleared',
            { trigger, email: email(), exit },
            [step('trigger', 'email'), step('email', 'exit')],
            { emailStep: 'email' },
            { email_sending_rate_limit: null },
        ],
        [
            'a long chain of steps after the email',
            chain.actions,
            chain.edges,
            { error: 'workflow_shape_not_supported', step: 'after_0' },
        ],
    ])('judges a send with files to %s', (_name, actions, edges, expected, settings = {}) => {
        const shape = filesWorkflowShape(flowOf(actions, edges, settings))

        if ('emailStep' in expected) {
            expect('emailStep' in shape && shape.emailStep.id).toBe(expected.emailStep)
            return
        }
        expect(shape).toEqual({
            refused: { error: expected.error, reason: expect.any(String), fix: expect.any(String) },
        })
        if ('refused' in shape && expected.step) {
            expect(shape.refused.reason).toContain(`"${expected.step}"`)
        }
    })
})
