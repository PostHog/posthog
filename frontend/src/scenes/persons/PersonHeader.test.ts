import { PersonType } from '~/types'
import { uuid } from 'lib/utils'
import { urls } from 'scenes/urls'
import { asDisplay, asLink } from 'scenes/persons/PersonHeader'

describe('the person header', () => {
    describe('linking to a person', () => {
        const personLinksTestCases = [
            { distinctIds: ['a uuid'], expectedLink: urls.person('a uuid'), name: 'with one id' },
            {
                distinctIds: ['the first uuid', 'a uuid'],
                expectedLink: urls.person('the first uuid'),
                name: 'with more than one id',
            },
            {
                distinctIds: [],
                expectedLink: undefined,
                name: 'with no ids',
            },
            {
                distinctIds: ['a+dicey/@!'],
                expectedLink: urls.person('a+dicey/@!'),
                name: 'with no ids',
            },
        ]

        personLinksTestCases.forEach((testCase) => {
            it(testCase.name, () => {
                expect(asLink({ distinct_ids: testCase.distinctIds })).toEqual(testCase.expectedLink)
            })
        })
    })

    const displayTestCases = [
        {
            isIdentified: true,
            props: {
                email: 'person@example.net',
            },
            personDisplay: 'person@example.net',

            describe: 'when person is identified',
            testName: 'if only email in person properties it shows identified people by email',
        },
        {
            isIdentified: true,
            props: {
                name: 'Mr Potato-head',
            },
            personDisplay: 'Mr Potato-head',

            describe: 'when person is identified',
            testName: 'if only name in person properties it shows identified people by name',
        },
        {
            isIdentified: true,
            props: {
                username: 'mr.potato.head',
            },
            personDisplay: 'mr.potato.head',

            describe: 'when person is identified',
            testName: 'if only username in person properties it shows identified people by username',
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
            testName: 'if there is a choice in person properties it shows identified people by email',
        },
        {
            isIdentified: true,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c'],
            props: {
                email: null,
            },
            personDisplay: 'User A9D1C',

            describe: 'when person is identified',
            testName: 'if there are no person properties it shows identified people by hash',
        },
        {
            isIdentified: false,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3babcde'],
            props: {
                email: null,
            },
            personDisplay: 'User ABCDE',

            describe: 'when person is unidentified',
            testName: 'if there are no person properties it shows people by hash',
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
            testName: 'if there are no person properties it shows people by hash',
        },
    ]

    displayTestCases.forEach((testCase) => {
        describe(testCase.describe, () => {
            const person: Partial<PersonType> = {
                distinct_ids: testCase.distinctIds || [uuid()],
                properties: testCase.props,
            }

            it(testCase.testName, () => {
                expect(asDisplay(person)).toEqual(testCase.personDisplay)
            })
        })
    })
})
