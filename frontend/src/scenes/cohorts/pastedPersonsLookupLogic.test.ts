import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { parsePastedPersonValues, pastedPersonsLookupLogic } from './pastedPersonsLookupLogic'

describe('pastedPersonsLookupLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        ['one line of emails', 'alice@example.com,bob@example.com', ['alice@example.com', 'bob@example.com']],
        ['emails on separate lines', 'alice@example.com\nbob@example.com\n', ['alice@example.com', 'bob@example.com']],
        [
            'quoted emails with spaces',
            '"alice@example.com", <bob@example.com>',
            ['alice@example.com', 'bob@example.com'],
        ],
        ['distinct IDs on separate lines', 'user-1\nuser-2\nuser-1', ['user-1', 'user-2']],
        ['a single email', 'alice@example.com', null],
        ['a full name', 'Alice Smith', null],
        ['a name with a comma', 'Smith, Alice', null],
    ])('parses %s', (_name, text, expected) => {
        expect(parsePastedPersonValues(text)).toEqual(expected)
    })

    it('selects matched persons, skips persons already in the cohort, and lists unmatched values', async () => {
        jest.spyOn(api, 'queryHogQL').mockImplementation(async (query) =>
            String(query).includes('person_distinct_ids')
                ? ({ results: [['person-3', 'user-3']] } as any)
                : ({
                      results: [
                          ['person-1', 'alice@example.com'],
                          ['person-2', 'bob@example.com'],
                      ],
                  } as any)
        )
        const onAddPerson = jest.fn()
        const logic = pastedPersonsLookupLogic({
            dataNodeKey: 'test',
            onAddPerson,
            existingPersonsSet: new Set(['person-2']),
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.lookupPastedValues(['Alice@example.com', 'bob@example.com', 'user-3', 'nobody@example.com'])
        })
            .toDispatchActions(['lookupPastedValuesSuccess'])
            .toMatchValues({
                lookupResult: {
                    matches: [
                        { personId: 'person-1', value: 'Alice@example.com' },
                        { personId: 'person-2', value: 'bob@example.com' },
                        { personId: 'person-3', value: 'user-3' },
                    ],
                    unmatched: ['nobody@example.com'],
                    truncated: false,
                },
            })

        expect(onAddPerson.mock.calls).toEqual([
            ['person-1', 'Alice@example.com'],
            ['person-3', 'user-3'],
        ])
    })
})
