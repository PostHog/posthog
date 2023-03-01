import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam, getPropertyDefinitions } from './api'
import { waitForExpect } from './expectations'

let organizationId: string

beforeAll(async () => {
    organizationId = await createOrganization()
})

test.concurrent(`event ingestion: definition for string property %p`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = 'distinctId'
    const uuid = new UUIDT().toString()

    await capture({
        teamId,
        distinctId,
        uuid,
        event: 'custom event',
        properties: {
            property: 'hehe',
        },
    })

    await waitForExpect(async () => {
        const propertyDefinitions = await getPropertyDefinitions(teamId)
        expect(propertyDefinitions).toContainEqual(
            expect.objectContaining({
                name: 'property',
                is_numerical: false,
                property_type: 'String',
            })
        )
    })
})

test.concurrent.each([[2], [2.1234], ['2'], ['2.1234']])(
    `event ingestion: definition for number property as number %p`,
    async (numberValue: any) => {
        const teamId = await createTeam(organizationId)
        const distinctId = 'distinctId'
        const uuid = new UUIDT().toString()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: 'custom event',
            properties: {
                property: numberValue,
            },
        })

        await waitForExpect(async () => {
            const propertyDefinitions = await getPropertyDefinitions(teamId)
            expect(propertyDefinitions).toContainEqual(
                expect.objectContaining({
                    name: 'property',
                    is_numerical: true,
                    property_type: 'Numeric',
                })
            )
        })
    }
)

test.concurrent.each([
    ['01/01/2020 00:00:00'],
    ['01-01-2020 00:00:00'],
    ['2020/01/01 00:00:00'],
    ['2020-01-01T00:00:00Z'],
    ['2020-01-01 00:00:00'],
    ['2020-01-01'],
])(`event ingestion: definition for date/datetime property should be datetime %p`, async (dateString: string) => {
    const teamId = await createTeam(organizationId)
    const distinctId = 'distinctId'
    const uuid = new UUIDT().toString()

    await capture({
        teamId,
        distinctId,
        uuid,
        event: 'custom event',
        properties: {
            property: dateString,
        },
    })

    await waitForExpect(async () => {
        const propertyDefinitions = await getPropertyDefinitions(teamId)
        expect(propertyDefinitions).toContainEqual(
            expect.objectContaining({
                name: 'property',
                is_numerical: false,
                property_type: 'DateTime',
            })
        )
    })
})

test.concurrent.each([[true], ['true']])(
    `event ingestion: definition for boolean property %p`,
    async (booleanValue: any) => {
        const teamId = await createTeam(organizationId)
        const distinctId = 'distinctId'
        const uuid = new UUIDT().toString()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: 'custom event',
            properties: {
                property: booleanValue,
            },
        })

        await waitForExpect(async () => {
            const propertyDefinitions = await getPropertyDefinitions(teamId)
            expect(propertyDefinitions).toContainEqual(
                expect.objectContaining({
                    name: 'property',
                    is_numerical: false,
                    property_type: 'Boolean',
                })
            )
        })
    }
)

test.concurrent.each([['utm_abc'], ['utm_123']])(
    `event ingestion: utm properties should always be strings`,
    async (propertyName: string) => {
        const teamId = await createTeam(organizationId)
        const distinctId = 'distinctId'
        const uuid = new UUIDT().toString()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: 'custom event',
            properties: {
                [propertyName]: 1234,
            },
        })

        await waitForExpect(async () => {
            const propertyDefinitions = await getPropertyDefinitions(teamId)
            expect(propertyDefinitions).toContainEqual(
                expect.objectContaining({
                    name: propertyName,
                    is_numerical: false,
                    property_type: 'String',
                })
            )
        })
    }
)
