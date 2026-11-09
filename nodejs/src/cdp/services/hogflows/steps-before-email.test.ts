import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '~/cdp/_tests/builders/hogflow.builder'

import { stepThatSetsVariablesBeforeEmail } from './steps-before-email'

type Actions = SimpleHogFlowRepresentation['actions']
type OutputVariable = Actions[string]['output_variable']

const trigger = { type: 'trigger', config: { type: 'api' } } as const
const email = (outputVariable?: OutputVariable) =>
    ({
        type: 'function_email',
        config: { template_id: 'template-email', inputs: {}, message_category_type: 'transactional' },
        output_variable: outputVariable,
    }) as const
const fetchUser = (outputVariable: OutputVariable) =>
    ({
        type: 'function',
        config: { template_id: 'template-webhook', inputs: {} },
        output_variable: outputVariable,
    }) as const
const exit = { type: 'exit', config: {} } as const
const step = (from: string, to: string) => ({ from, to, type: 'continue' as const })
const flowOf = (actions: Actions, edges: SimpleHogFlowRepresentation['edges']) =>
    new FixtureHogFlowBuilder().withWorkflow({ actions, edges }).build()

describe('stepThatSetsVariablesBeforeEmail', () => {
    it.each<[string, Actions, SimpleHogFlowRepresentation['edges'], string | null]>([
        [
            'the generated workflow, a trigger, an email step and an exit',
            { trigger, email: email(), exit },
            [step('trigger', 'email'), step('email', 'exit')],
            null,
        ],
        [
            'a step that stores its output before the email',
            { trigger, fetch: fetchUser({ key: 'user' }), email: email() },
            [step('trigger', 'fetch'), step('fetch', 'email')],
            'fetch',
        ],
        [
            'a step that stores its output as a list before the email',
            { trigger, fetch: fetchUser([{ key: 'user', result_path: 'body' }]), email: email() },
            [step('trigger', 'fetch'), step('fetch', 'email')],
            'fetch',
        ],
        [
            'a step with an output variable without a key before the email',
            { trigger, fetch: fetchUser({ key: '' }), email: email() },
            [step('trigger', 'fetch'), step('fetch', 'email')],
            null,
        ],
        [
            'a step with an empty list of output variables before the email',
            { trigger, fetch: fetchUser([]), email: email() },
            [step('trigger', 'fetch'), step('fetch', 'email')],
            null,
        ],
        [
            'a step that stores its output only after the email',
            { trigger, email: email(), fetch: fetchUser({ key: 'user' }) },
            [step('trigger', 'email'), step('email', 'fetch')],
            null,
        ],
        [
            'an email step that stores its output and no email after it',
            { trigger, email: email({ key: 'sent' }), exit },
            [step('trigger', 'email'), step('email', 'exit')],
            null,
        ],
        [
            'an email step that stores its output before a second email',
            { trigger, first: email({ key: 'sent' }), email: email() },
            [step('trigger', 'first'), step('first', 'email')],
            'first',
        ],
        [
            'an email step that stores its output and loops back to itself',
            { trigger, email: email({ key: 'sent' }) },
            [step('trigger', 'email'), step('email', 'email')],
            'email',
        ],
        [
            'a step that stores its output but the trigger never reaches',
            { trigger, email: email(), fetch: fetchUser({ key: 'user' }), later: email() },
            [step('trigger', 'email'), step('fetch', 'later')],
            null,
        ],
    ])('names the step that sets variables before an email in %s', (_name, actions, edges, expectedStepId) => {
        expect(stepThatSetsVariablesBeforeEmail(flowOf(actions, edges))?.id ?? null).toBe(expectedStepId)
    })
})
