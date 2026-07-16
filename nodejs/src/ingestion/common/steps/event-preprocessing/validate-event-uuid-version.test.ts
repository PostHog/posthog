import { PipelineResultType, ok } from '~/ingestion/framework/results'
import { createTestPipelineEvent } from '~/tests/helpers/pipeline-event'

import { KNOWN_NON_V7_LIBS, createValidateEventUuidVersionStep } from './validate-event-uuid-version'

const UUID_V7 = '017f22e2-79b0-7cc3-98c4-dc0c0c07398f'
const UUID_V4 = 'f47ac10b-58cc-4372-a567-0e02b2c3d479'
const UUID_V1 = '61f0c404-5cb3-11e7-907b-a6006ad3dba0'

const NON_V7_UUIDS: [string, string][] = [
    [UUID_V4, 'v4'],
    [UUID_V1, 'v1'],
]

describe('createValidateEventUuidVersionStep', () => {
    const allowedLibs = new Set(['posthog-python', 'posthog-go'])
    const step = createValidateEventUuidVersionStep(allowedLibs)

    const createInput = (uuid: string, lib?: unknown) => ({
        event: createTestPipelineEvent({
            uuid,
            event: 'custom_event',
            distinct_id: 'user123',
            team_id: 1,
            properties: lib === undefined ? {} : { $lib: lib },
        }),
    })

    const expectAllowed = async (input: ReturnType<typeof createInput>) => {
        const result = await step(input)
        expect(result).toEqual(ok(input))
    }

    it.each(['web', 'posthog-python', 'posthog-node', ''])('allows v7 uuids regardless of $lib (%p)', async (lib) => {
        await expectAllowed(createInput(UUID_V7, lib))
    })

    it.each(NON_V7_UUIDS)('allows %s uuid from an allowlisted lib', async (uuid) => {
        await expectAllowed(createInput(uuid, 'posthog-python'))
    })

    it.each(NON_V7_UUIDS)('warns on %s uuid from a non-allowlisted lib', async (uuid, version) => {
        const input = createInput(uuid, 'posthog-cobol')
        const result = await step(input)
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toEqual({
                type: 'event_uuid_not_v7',
                details: {
                    eventUuid: uuid,
                    event: 'custom_event',
                    distinctId: 'user123',
                    lib: 'posthog-cobol',
                },
                key: 'posthog-cobol',
            })
            // sanity: the fixtures really are non-v7
            expect(version).not.toBe('v7')
        }
    })

    it('warns on a non-v7 uuid with a missing $lib (keyed by empty string)', async () => {
        const input = createInput(UUID_V4, undefined)
        const result = await step(input)
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toMatchObject({ type: 'event_uuid_not_v7', details: { lib: '' }, key: '' })
        }
    })

    it.each(['not-a-uuid', '', '12345'])('does not warn on a malformed/missing uuid (%p)', async (uuid) => {
        await expectAllowed(createInput(uuid, 'posthog-cobol'))
    })

    describe('with the default (production) allowlist', () => {
        const defaultStep = createValidateEventUuidVersionStep()

        it.each(['posthog-python', 'posthog-go', 'posthog-dotnet', 'posthog-ruby', 'web', ''])(
            'does not warn for first-party lib %p sending a v4 uuid',
            async (lib) => {
                const input = { event: createTestPipelineEvent({ uuid: UUID_V4, properties: { $lib: lib } }) }
                const result = await defaultStep(input)
                expect(result).toEqual(ok(input))
            }
        )

        it('warns for a lib outside the allowlist sending a v4 uuid', async () => {
            const input = { event: createTestPipelineEvent({ uuid: UUID_V4, properties: { $lib: 'acme-custom-sdk' } }) }
            const result = await defaultStep(input)
            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0].type).toBe('event_uuid_not_v7')
            }
        })

        it('allowlist contains the in-flight v4 SDKs', () => {
            for (const lib of ['posthog-python', 'posthog-go', 'posthog-dotnet', 'posthog-ruby']) {
                expect(KNOWN_NON_V7_LIBS.has(lib)).toBe(true)
            }
        })
    })
})
