import { SANDBOX_EMAIL_SENDER_NOTE } from 'lib/integrations/sandboxEmailSender'

import { IntegrationType } from '~/types'

import { selectSenders, senderHintFor, senderOptions } from './selectSenders'

describe('selectSenders', () => {
    const current = { integrationId: 1, email: 'custom@example.com', name: 'Custom' }

    it.each([
        {
            case: 'picking the sandbox sender keeps only it and drops the custom sender values',
            ids: [1, 2, 7],
            sandboxId: 7,
            expected: { integrationId: 7, integrationIds: undefined, email: undefined, name: undefined },
        },
        {
            case: 'adding an own sender while the sandbox sender is selected drops the sandbox sender',
            value: { integrationId: 7 },
            ids: [7, 1],
            sandboxId: 7,
            expected: { integrationId: 1, integrationIds: undefined },
        },
        {
            case: 'own senders rotate and keep the custom sender values',
            ids: [1, 2],
            sandboxId: 7,
            expected: { integrationId: 1, integrationIds: [1, 2], email: 'custom@example.com', name: 'Custom' },
        },
        {
            case: 'picking the sandbox sender over a full rotation still works',
            ids: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 7],
            sandboxId: 7,
            expected: { integrationId: 7, integrationIds: undefined },
        },
        {
            case: 'a surface without the sandbox sender treats its id like any other',
            ids: [1, 7],
            sandboxId: undefined,
            expected: { integrationId: 1, integrationIds: [1, 7] },
        },
        {
            case: 'more senders than the limit are refused',
            ids: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12],
            sandboxId: 7,
            expected: null,
        },
    ])('$case', ({ value = current, ids, sandboxId, expected }) => {
        expect(selectSenders(value, ids, sandboxId)).toEqual(
            expected === null ? null : expect.objectContaining(expected)
        )
    })

    describe('senderOptions', () => {
        const own = { id: 1, kind: 'email', display_name: 'Own sender' } as IntegrationType
        const sandbox = { id: 7, kind: 'email', display_name: 'Sandbox sender' } as IntegrationType
        const sandboxLabel = {} as JSX.Element

        it.each([
            {
                case: 'nothing is offered before the integrations load',
                integrations: null,
                sandboxSender: sandbox,
                expected: null,
            },
            {
                case: 'the sandbox sender comes last and only it carries the tag label',
                integrations: [own, sandbox],
                sandboxSender: sandbox,
                expected: [
                    { key: '1', label: 'Own sender', value: 1 },
                    { key: '7', label: 'Sandbox sender', value: 7, labelComponent: sandboxLabel },
                ],
            },
            {
                case: 'without a sandbox sender only own senders are offered',
                integrations: [own],
                sandboxSender: null,
                expected: [{ key: '1', label: 'Own sender', value: 1 }],
            },
        ])('$case', ({ integrations, sandboxSender, expected }) => {
            expect(senderOptions(integrations, [own], sandboxSender, () => sandboxLabel)).toEqual(expected)
        })
    })

    describe('senderHintFor', () => {
        it.each([
            {
                case: 'the sandbox note wins over the rotation hint',
                sandbox: true,
                rotation: true,
                expected: SANDBOX_EMAIL_SENDER_NOTE,
            },
            {
                case: 'rotation shows the sender limit',
                sandbox: false,
                rotation: true,
                expected: expect.stringContaining('Choose up to'),
            },
            { case: 'a single own sender shows no hint', sandbox: false, rotation: false, expected: null },
        ])('$case', ({ sandbox, rotation, expected }) => {
            expect(senderHintFor(sandbox, rotation)).toEqual(expected)
        })
    })
})
