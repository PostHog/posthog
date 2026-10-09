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
        [
            'display names with addresses',
            '"Smith, Alice" <alice@example.com>; Bob Jones <bob@example.com>\nCarol <carol@example.com>',
            ['alice@example.com', 'bob@example.com', 'carol@example.com'],
        ],
        [
            'display names with addresses on one line',
            'Alice <alice@example.com>, Bob <bob@example.com>',
            ['alice@example.com', 'bob@example.com'],
        ],
        ['distinct IDs on separate lines', 'user-1\nuser-2\nuser-1', ['user-1', 'user-2']],
        ['distinct IDs with commas and spaces', 'user,1\nuser,2\nJane Doe', ['user,1', 'user,2', 'Jane Doe']],
        ['a single email', 'alice@example.com', null],
        ['a full name', 'Alice Smith', null],
        ['a name with a comma', 'Smith, Alice', null],
    ])('parses %s', (_name, text, expected) => {
        expect(parsePastedPersonValues(text)).toEqual(expected)
    })

    it('selects every matched person, skips persons already in the cohort, and lists unmatched values', async () => {
        jest.spyOn(api, 'queryHogQL').mockImplementation(async (query) =>
            String(query).includes('person_distinct_ids')
                ? ({
                      results: [
                          ['person-3', 'user-3'],
                          ['person-5', 'alice@example.com'],
                      ],
                  } as any)
                : ({
                      results: [
                          ['alice@example.com', ['person-1']],
                          ['bob@example.com', ['person-2', 'person-4']],
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
                        { personId: 'person-4', value: 'bob@example.com' },
                        { personId: 'person-3', value: 'user-3' },
                    ],
                    unmatched: ['nobody@example.com'],
                    alreadyInCohortCount: 1,
                    truncated: false,
                },
            })

        expect(onAddPerson.mock.calls).toEqual([
            ['person-1', 'Alice@example.com'],
            ['person-4', 'bob@example.com'],
            ['person-3', 'user-3'],
        ])
    })
})
