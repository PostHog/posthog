import { BuiltLogic } from 'kea'

import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { PersonType } from '~/types'
import { uuid } from 'lib/utils'
import { personHeaderLogic } from 'scenes/persons/personHeaderLogic'
import { personHeaderLogicType } from 'scenes/persons/personHeaderLogicType'
import { urls } from 'scenes/urls'

jest.mock('lib/utils', () => ({
    uuid: jest.fn().mockImplementation(() => 'abcde'),
}))

describe('the person header', () => {
    let logic: BuiltLogic<personHeaderLogicType>

    describe('with no props', () => {
        initKeaTestLogic({
            logic: personHeaderLogic,
            props: {},
            onLogic: (l) => (logic = l),
        })
        it('has expected defaults', () => {
            expectLogic(logic).toMatchValues({
                withIcon: false,
                personDisplay: 'Unidentified with no ids',
                personLink: '',
                isIdentified: false,
            })
        })
    })

    const personLinksTestCases = [
        { distinctIds: ['a uuid'], expectedLink: urls.person('a uuid'), name: 'with one id' },
        {
            distinctIds: ['the first uuid', 'a uuid'],
            expectedLink: urls.person('the first uuid'),
            name: 'with more than one id',
        },
        {
            distinctIds: [],
            expectedLink: '',
            name: 'with no ids',
        },
    ]

    personLinksTestCases.forEach((testCase) => {
        describe('linking to a person', () => {
            initKeaTestLogic({
                logic: personHeaderLogic,
                props: { withIcon: true, person: { distinct_ids: testCase.distinctIds } },
                onLogic: (l) => (logic = l),
            })

            it(testCase.name, () => {
                expectLogic(logic).toMatchValues({ personLink: testCase.expectedLink })
            })
        })
    })

    describe('with an identified person in props', () => {
        initKeaTestLogic({
            logic: personHeaderLogic,
            props: { withIcon: true, person: { is_identified: true } },
            onLogic: (l) => (logic = l),
        })

        it('reports the user is identified', () => {
            expectLogic(logic).toMatchValues({ isIdentified: true })
        })
    })

    describe('withIcon props', () => {
        initKeaTestLogic({
            logic: personHeaderLogic,
            props: { withIcon: true },
            onLogic: (l) => (logic = l),
        })

        it('can set whether to show an icon from props', () => {
            expectLogic(logic).toMatchValues({ withIcon: true })
        })
    })

    describe('it sets a key when props has a person', () => {
        const props = {
            withIcon: true,
            person: {
                is_identified: false,
                distinct_ids: [uuid()],
                properties: { email: null },
            },
        }
        initKeaTestLogic({
            logic: personHeaderLogic,
            props: props,
            onLogic: (l) => (logic = l),
        })

        it('is a hash', async () => {
            await expectLogic(logic).then(() => {
                expect(logic.key).toEqual('2442792429')
            })
        })
    })

    describe('it sets a key when props has no person', () => {
        const props = {
            withIcon: true,
            person: null,
        }
        initKeaTestLogic({
            logic: personHeaderLogic,
            props: props,
            onLogic: (l) => (logic = l),
        })

        it('to a string "unidentified"', async () => {
            await expectLogic(logic).then(() => {
                expect(logic.key).toEqual('unidentified')
            })
        })
    })

    const displayTestCases = [
        {
            isIdentified: true,
            props: {
                email: 'person@example.net',
            },
            expectedState: {
                personDisplay: 'person@example.net',
            },
            describe: 'when person is identified',
            testName: 'if only email in person properties it shows identified people by email',
        },
        {
            isIdentified: true,
            props: {
                name: 'Mr Potato-head',
            },
            expectedState: {
                personDisplay: 'Mr Potato-head',
            },
            describe: 'when person is identified',
            testName: 'if only name in person properties it shows identified people by name',
        },
        {
            isIdentified: true,
            props: {
                username: 'mr.potato.head',
            },
            expectedState: {
                personDisplay: 'mr.potato.head',
            },
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
            expectedState: {
                personDisplay: 'person@example.com',
            },
            describe: 'when person is identified',
            testName: 'if there is a choice in person properties it shows identified people by email',
        },
        {
            isIdentified: true,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c'],
            props: {
                email: null,
            },
            expectedState: {
                personDisplay: 'Identified user A9D1C',
            },
            describe: 'when person is identified',
            testName: 'if there are no person properties it shows identified people by hash',
        },
        {
            isIdentified: false,
            distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3babcde'],
            props: {
                email: null,
            },
            expectedState: {
                personDisplay: 'Unidentified user ABCDE',
            },
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
            expectedState: {
                personDisplay: 'Unidentified example@person.com',
            },
            describe: 'when person is unidentified',
            testName: 'if there are no person properties it shows people by hash',
        },
    ]

    displayTestCases.forEach((testCase) => {
        describe(testCase.describe, () => {
            const person: Partial<PersonType> = {
                is_identified: testCase.isIdentified,
                distinct_ids: testCase.distinctIds || [uuid()],
                properties: testCase.props,
            }

            initKeaTestLogic({
                logic: personHeaderLogic,
                props: { person },
                onLogic: (l) => (logic = l),
            })

            it(testCase.testName, () => {
                expectLogic(logic).toMatchValues(testCase.expectedState)
            })
        })
    })
})
