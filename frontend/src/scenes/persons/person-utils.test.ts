import { uuid } from 'lib/utils'
import { urls } from 'scenes/urls'

import { PersonType } from '~/types'

import { asDisplay, asLink, getPersonColorIndex } from './person-utils'

describe('the person header', () => {
    describe('linking to a person', () => {
        const personLinksTestCases = [
            { distinctIds: ['a uuid'], expectedLink: urls.personByDistinctId('a uuid'), name: 'with one id' },
            {
                distinctIds: ['the first uuid', 'a uuid'],
                expectedLink: urls.personByDistinctId('the first uuid'),
                name: 'with more than one id',
            },
            {
                distinctIds: [],
                expectedLink: undefined,
                name: 'with no ids',
            },
            {
                distinctIds: ['a+dicey/@!'],
                expectedLink: urls.personByDistinctId('a+dicey/@!'),
                name: 'with no ids',
            },
        ]

        it.each(personLinksTestCases.map((testCase) => [testCase.name, testCase]))(
            'returns a link %s',
            (_, testCase) => {
                expect(asLink({ distinct_ids: testCase.distinctIds })).toEqual(testCase.expectedLink)
            }
        )
    })

    const displayTestCases = [
        {
            isIdentified: true,
            props: {
                email: 'person@example.net',
            },
            personDisplay: 'person@example.net',

            describe: 'when person is identified',
            testName: 'if only email in person properties, shows identified people by email',
        },
        {
            isIdentified: true,
            props: {
                name: 'Mr Potato-head',
            },
            personDisplay: 'Mr Potato-head',

            describe: 'when person is identified',
            testName: 'if only name in person properties, shows identified people by name',
        },
        {
            isIdentified: true,
            props: {
                username: 'mr.potato.head',
            },
            personDisplay: 'mr.potato.head',

            describe: 'when person is identified',
            testName: 'if only username in person properties, shows identified people by username',
        },
        {
            isIdentified: true,
            props: {
                email: 'person@example.com',
                name: 'Mr Person',
                username: 'mr.potato.head',
            },
            personDisplay: 'person@example.com',

            describe: 'when person is identified',
            testName: 'if there is a choice in person properties, shows identified people by email',
        },
        {
            isIdentified: true,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c'],
            props: {
                email: null,
            },
            personDisplay: '03b16e4c0b14ef-00000…c680-17878af3ba9d1c',

            describe: 'when person is identified',
            testName: 'if there are no person properties, shows identified people by distinct ID',
        },
        {
            isIdentified: true,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c', '1234abc'],
            props: {
                email: null,
            },
            personDisplay: '1234abc',
            describe: 'when person is identified',
            testName:
                'if there are no person properties, shows identified people by distinct ID, preferring non-anon IDs',
        },
        {
            isIdentified: true,
            // The second ID has an "@" and a "." but is NOT an email
            distinctIds: [
                '03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c',
                '1234.abc@',
                'juliatusk@gmail.com',
            ],
            props: {
                email: null,
            },
            personDisplay: 'juliatusk@gmail.com',
            describe: 'when person is identified',
            testName:
                'if there are no person properties, shows identified people by distinct ID, preferring email-like',
        },
        {
            isIdentified: false,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3babcde'],
            props: {
                email: null,
            },
            personDisplay: '03b16e4c0b14ef-00000…c680-17878af3babcde',

            describe: 'when person is unidentified',
            testName: 'if there are no person properties, shows people by distinct ID',
        },
        {
            isIdentified: false,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3bzyxwv'],
            props: {
                email: 'example@person.com',
                name: 'is not preferred over email',
            },
            personDisplay: 'example@person.com',

            describe: 'when person is unidentified',
            testName: 'if there are no person properties, shows people by distinct ID',
        },
    ]

    it.each(displayTestCases.map((testCase) => [testCase.describe, testCase]))('displays person %s', (_, testCase) => {
        const person: Pick<PersonType, 'distinct_ids' | 'properties'> = {
            distinct_ids: testCase.distinctIds || [uuid()],
            properties: testCase.props,
        }

        expect(asDisplay(person)).toEqual(testCase.personDisplay)
    })

    describe('color index', () => {
        it('returns undefined for null/undefined identifier', () => {
            expect(getPersonColorIndex(null)).toBeUndefined()
            expect(getPersonColorIndex(undefined)).toBeUndefined()
        })

        it('returns a number between 0 and 15', () => {
            for (let i = 0; i < 26; i++) {
                const letter = String.fromCharCode(97 + i) // a-z
                const idx = getPersonColorIndex(`user-1234${letter}`)
                expect(idx).toBeGreaterThanOrEqual(0)
                expect(idx).toBeLessThanOrEqual(15)
            }
        })

        it('returns consistent index for the same identifier', () => {
            const index1 = getPersonColorIndex('user-abc-123')
            const index2 = getPersonColorIndex('user-abc-123')
            expect(index1).toEqual(index2)
        })

        it('returns different indices for identifiers starting with the same character', () => {
            // This is the key test: identifiers starting with same char should get different colors
            const index1 = getPersonColorIndex('0abc123')
            const index2 = getPersonColorIndex('0xyz789')
            const index3 = getPersonColorIndex('0different')

            // At least two of these should be different (with good hash distribution)
            const uniqueIndices = new Set([index1, index2, index3])
            expect(uniqueIndices.size).toBe(3)
        })
    })
})
