import type {
    WorkLineApi,
    WorkOptionApi,
    WorkOptionKindEnumApi,
    WorkStepApi,
    WorkThreadApi,
} from 'products/today/frontend/generated/api.schemas'

import { checkoutWorkThread, finishedWorkThread } from './workThreadFixtures'
import {
    isWorkStepExpanded,
    nextWorkOption,
    workLines,
    workStepByKey,
    workStepState,
    workThreadSummary,
} from './workThreadState'

function option(key: string, kind: WorkOptionKindEnumApi, gate: string | null = null): WorkOptionApi {
    return {
        key,
        kind,
        label: key,
        why: `Why ${key}`,
        gate,
        helper: {
            mode: 'in_place',
            product: 'Feature flags',
            does: `Does ${key}`,
            fields: [],
            run_label: 'Run',
            run: { type: 'action', to: null, action_id: key, params: null },
            mcp_tools: [],
        },
    }
}

function step(key: string, options: WorkOptionApi[] = [], alongside: WorkLineApi[] = []): WorkStepApi {
    return {
        key,
        title: key,
        description: '',
        area: 'Release',
        item: null,
        facts: [],
        chosen_label: null,
        started_from: null,
        options,
        alongside,
    }
}

function line(key: string, steps: WorkStepApi[]): WorkLineApi {
    return { key, steps }
}

function thread(main: WorkLineApi): WorkThreadApi {
    return { key: 'thread', name: 'Thread', line: main }
}

describe('workThreadState', () => {
    test('workLines lists the line, then each alongside line depth first', () => {
        const nested = line('nested', [step('n1')])
        const first = line('first', [step('f1', [], [nested])])
        const second = line('second', [step('s1')])
        const main = line('main', [step('m1', [], [first]), step('m2', [], [second])])

        expect(workLines(main).map((l) => l.key)).toEqual(['main', 'first', 'nested', 'second'])
    })

    test.each<[string, WorkOptionApi[], 'first' | 'last', string]>([
        ['an earlier step with an ungated next option is done', [], 'first', 'done'],
        ['the last step with no options is done', [], 'last', 'done'],
        ['the last step with only alongside options is done', [option('a', 'alongside')], 'last', 'done'],
        [
            'the last step whose next options are all gated is waiting',
            [option('a', 'next', 'Opens later'), option('b', 'next', 'Opens later')],
            'last',
            'waiting',
        ],
        [
            'an ungated alongside option does not stop the last step waiting',
            [option('a', 'next', 'Opens later'), option('b', 'alongside')],
            'last',
            'waiting',
        ],
        [
            'the last step with one ungated next option needs you',
            [option('a', 'next', 'Opens later'), option('b', 'next')],
            'last',
            'needs_you',
        ],
    ])('workStepState: %s', (_name, lastOptions, which, expected) => {
        const first = step('first', [option('go', 'next')])
        const last = step('last', lastOptions)
        expect(workStepState(line('main', [first, last]), which === 'first' ? first : last)).toEqual(expected)
    })

    test.each([
        ['an earlier step that shares its item with a later one', finishedWorkThread, 'rolled-out', '100% for 34 days'],
        ['a step on an alongside line', checkoutWorkThread, 'early-access-open', '6 so far'],
        ['no step for an unknown key', checkoutWorkThread, 'missing', null],
    ])('workStepByKey finds %s', (_name, workThread, stepKey, firstFact) => {
        expect(workStepByKey(workThread, stepKey)?.facts[0]?.value ?? null).toEqual(firstFact)
    })

    test.each<[string, 'done' | 'needs_you' | 'waiting', boolean | undefined, boolean]>([
        ['a done step is collapsed by default', 'done', undefined, false],
        ['a step that needs you is expanded by default', 'needs_you', undefined, true],
        ['a waiting step is expanded by default', 'waiting', undefined, true],
        ['a person can expand a done step', 'done', true, true],
        ['a person can collapse a step that needs you', 'needs_you', false, false],
    ])('isWorkStepExpanded: %s', (_name, state, override, expected) => {
        expect(isWorkStepExpanded(state, override)).toEqual(expected)
    })

    test.each([
        ['checkout', checkoutWorkThread, { steps: 4, inOrder: 3, alongside: 1, needsYou: 1, waiting: 1, done: 2 }],
        ['finished', finishedWorkThread, { steps: 2, inOrder: 2, alongside: 0, needsYou: 0, waiting: 0, done: 2 }],
    ])('workThreadSummary counts every line of the %s thread', (_name, workThread, expected) => {
        expect(workThreadSummary(workThread)).toEqual(expected)
    })

    test.each<[string, WorkThreadApi, { step: string; option: string } | null]>([
        ['the checkout thread', checkoutWorkThread, { step: 'experiment-result', option: 'ship-winner' }],
        ['a finished thread', finishedWorkThread, null],
        [
            'a thread whose first next option is gated',
            thread(line('main', [step('only', [option('gated', 'next', 'Opens later'), option('open', 'next')])])),
            { step: 'only', option: 'open' },
        ],
        [
            'a thread whose main line waits while an alongside line needs you',
            thread(
                line('main', [
                    step('m1', [], [line('side', [step('s1', [option('side-go', 'next')])])]),
                    step('m2', [option('gated', 'next', 'Opens later')]),
                ])
            ),
            { step: 's1', option: 'side-go' },
        ],
        [
            'a thread where the main line and an alongside line both need you',
            thread(
                line('main', [
                    step('m1', [], [line('side', [step('s1', [option('side-go', 'next')])])]),
                    step('m2', [option('main-go', 'next')]),
                ])
            ),
            { step: 'm2', option: 'main-go' },
        ],
    ])('nextWorkOption for %s', (_name, workThread, expected) => {
        const next = nextWorkOption(workThread)
        expect(next ? { step: next.step.key, option: next.option.key } : null).toEqual(expected)
    })
})
