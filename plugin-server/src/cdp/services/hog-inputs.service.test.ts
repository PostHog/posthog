import { DateTime } from 'luxon'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { createHogExecutionGlobals, createHogFunction, insertIntegration } from '../_tests/fixtures'
import { compileHog } from '../templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { formatHogInput, HogInputsService } from './hog-inputs.service'

describe('Hog Inputs', () => {
    let hub: Hub
    let team: Team
    let hogInputsService: HogInputsService

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        await insertIntegration(hub.postgres, team.id, {
            id: 1,
            kind: 'slack',
            config: { team: 'foobar' },
            sensitive_config: {
                access_token: hub.encryptedFields.encrypt('token'),
                not_encrypted: 'not-encrypted',
            },
        })

        hogInputsService = new HogInputsService(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('formatInput', () => {
        it('can handle null values in input objects', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            // Body with null values that should be preserved
            const inputWithNulls = {
                body: {
                    value: {
                        event: '{event}',
                        person: null,
                        userId: null,
                    },
                },
            }

            // Call formatInput directly to test that it handles null values
            const result = await formatHogInput(inputWithNulls, globals)

            // Verify that null values are preserved
            expect(result.body.value.person).toBeNull()
            expect(result.body.value.userId).toBeNull()
            expect(result.body.value.event).toBe('{event}')
        })

        it('can handle deep null and undefined values', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            const complexInput = {
                body: {
                    value: {
                        data: {
                            first: null,
                            second: undefined,
                            third: {
                                nested: null,
                            },
                        },
                    },
                },
            }

            const result = await formatHogInput(complexInput, globals)

            // Verify all null and undefined values are properly preserved
            expect(result.body.value.data.first).toBeNull()
            expect(result.body.value.data.second).toBeUndefined()
            expect(result.body.value.data.third.nested).toBeNull()
        })
    })

    describe('buildInputs', () => {
        let hogFunction: HogFunctionType
        let globals: HogFunctionInvocationGlobals

        beforeEach(async () => {
            hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {
                    hog_templated: {
                        value: 'event: "{event.event}"',
                        templating: 'hog',
                        bytecode: await compileHog('return f\'event: "{event.event}"\''),
                    },
                    liquid_templated: {
                        value: 'event: "{{ event.event }}"',
                        templating: 'liquid',
                    },
                    slack: { value: 1 },
                },
                inputs_schema: [
                    { key: 'hog_templated', type: 'string', required: true },
                    { key: 'slack', type: 'integration', required: true },
                ],
            })

            globals = createHogExecutionGlobals()
        })

        it('should template out hog inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.hog_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        it('should template out liquid inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.liquid_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        it('should loads inputs with integration inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.slack).toMatchInlineSnapshot(`
                {
                  "access_token": "token",
                  "not_encrypted": "not-encrypted",
                  "team": "foobar",
                }
            `)
        })

        it('should not load integrations from a different team', async () => {
            hogFunction.team_id = 100

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.slack).toMatchInlineSnapshot(`1`)
        })
    })
})
