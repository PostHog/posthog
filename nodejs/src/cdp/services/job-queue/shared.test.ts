import { parseJSON } from '~/common/utils/json-parse'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../../_tests/examples'
import { createHogExecutionGlobals, createHogFunction } from '../../_tests/fixtures'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../../types'
import { EncryptedFields } from '../../utils/encryption-utils'
import { markServerResolvedIntegration, signIntegrationRef } from '../../utils/integration-input-refs'
import { createInvocation } from '../../utils/invocation-utils'
import { openSealedState, v2JobToInvocation } from '../cyclotron-v2/job-codec'
import { serializeInvocation } from './job-queue-kafka'
import { invocationToV2JobInit } from './job-queue-postgres-v2'
import { createInvocationSanitizer, sanitizeInvocationForPersistence } from './shared'

const ENCRYPTION_SALT_KEYS = '00beef0000beef0000beef0000beef00'

describe('sanitizeInvocationForPersistence', () => {
    const exampleHogFunction = createHogFunction({
        name: 'Test hog function',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
    })

    const exampleGroups = {
        organization: {
            id: 'org-1',
            type: 'organization',
            index: 0,
            url: 'http://localhost:8000/groups/0/org-1',
            properties: { name: 'PostHog', employee_count: 100 },
        },
    }

    it('should strip groups from state.globals', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({ groups: exampleGroups }),
                inputs: {},
            },
            exampleHogFunction
        )

        expect(invocation.state.globals.groups).toBeDefined()

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized.state!.globals.groups).toBeUndefined()
        // Original should not be mutated
        expect(invocation.state.globals.groups).toBeDefined()
    })

    it('should preserve all other state fields', () => {
        const globals = {
            ...createHogExecutionGlobals({ groups: exampleGroups }),
            inputs: { url: 'https://example.com' },
        }
        const invocation = createInvocation(globals, exampleHogFunction)

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized.state!.globals.event).toEqual(invocation.state.globals.event)
        expect(sanitized.state!.globals.person).toEqual(invocation.state.globals.person)
        expect(sanitized.state!.globals.project).toEqual(invocation.state.globals.project)
        expect(sanitized.state!.globals.inputs).toEqual(invocation.state.globals.inputs)
        expect(sanitized.state!.timings).toEqual(invocation.state.timings)
        expect(sanitized.teamId).toEqual(invocation.teamId)
        expect(sanitized.functionId).toEqual(invocation.functionId)
    })

    it('should return original invocation when no groups present', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({ groups: undefined }),
                inputs: {},
            },
            exampleHogFunction
        )
        delete invocation.state.globals.groups

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized).toBe(invocation)
    })

    it('should return original invocation when groups is empty', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals(),
                inputs: {},
            },
            exampleHogFunction
        )

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized).toBe(invocation)
    })

    it('should handle invocations without state.globals (e.g. hogflow)', () => {
        const invocation = {
            id: 'test-id',
            teamId: 1,
            functionId: 'func-1',
            queue: 'hogflow' as const,
            queuePriority: 0,
            state: {
                event: {
                    uuid: 'test',
                    event: 'test',
                    distinct_id: 'test',
                    properties: {},
                    elements_chain: '',
                    timestamp: '',
                    url: '',
                },
                actionStepCount: 0,
            },
        }

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized).toBe(invocation)
    })

    it('should strip multiple group types', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({
                    groups: {
                        ...exampleGroups,
                        company: {
                            id: 'company-1',
                            type: 'company',
                            index: 1,
                            url: 'http://localhost:8000/groups/1/company-1',
                            properties: { name: 'Acme Inc', revenue: 1000000 },
                        },
                    },
                }),
                inputs: {},
            },
            exampleHogFunction
        )

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized.state!.globals.groups).toBeUndefined()
        expect(sanitized.state!.globals.event).toBeDefined()

        // Original retains both groups
        expect(Object.keys(invocation.state.globals.groups!)).toEqual(['organization', 'company'])
    })

    it('should strip person when stripPerson is true', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({ groups: undefined }),
                inputs: {},
            },
            exampleHogFunction
        )
        delete invocation.state.globals.groups

        expect(invocation.state.globals.person).toBeDefined()

        const sanitized = sanitizeInvocationForPersistence(invocation, { stripPerson: true })

        expect(sanitized.state!.globals.person).toBeUndefined()
        // Original should not be mutated
        expect(invocation.state.globals.person).toBeDefined()
    })

    it('should not strip person by default', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({ groups: exampleGroups }),
                inputs: {},
            },
            exampleHogFunction
        )

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized.state!.globals.person).toEqual(invocation.state.globals.person)
        expect(sanitized.state!.globals.groups).toBeUndefined()
    })

    it.each([
        { stripPerson: true, expectPerson: false },
        { stripPerson: false, expectPerson: true },
    ])('should always strip groups and strip person when stripPerson=$stripPerson', ({ stripPerson, expectPerson }) => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({ groups: exampleGroups }),
                inputs: {},
            },
            exampleHogFunction
        )

        const sanitized = sanitizeInvocationForPersistence(invocation, { stripPerson })

        expect(sanitized.state!.globals.groups).toBeUndefined()

        if (expectPerson) {
            expect(sanitized.state!.globals.person).toBeDefined()
        } else {
            expect(sanitized.state!.globals.person).toBeUndefined()
        }
    })
})

describe('createInvocationSanitizer', () => {
    const exampleHogFunction = createHogFunction({
        name: 'Test hog function',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
    })

    const exampleGroups = {
        organization: {
            id: 'org-1',
            type: 'organization',
            index: 0,
            url: 'http://localhost:8000/groups/0/org-1',
            properties: { name: 'PostHog' },
        },
    }

    it('should strip groups from invocations', () => {
        const sanitizer = createInvocationSanitizer({
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
            ENCRYPTION_SALT_KEYS,
        })
        const invocation = createInvocation(
            { ...createHogExecutionGlobals({ groups: exampleGroups }), inputs: {} },
            exampleHogFunction
        )

        const [sanitized] = sanitizer.sanitizeInvocations([invocation])
        expect(sanitized.state!.globals.groups).toBeUndefined()
        expect(sanitized.state!.globals.person).toBeDefined()
    })

    it('should strip person for configured teams', () => {
        const sanitizer = createInvocationSanitizer({
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '2',
            ENCRYPTION_SALT_KEYS,
        })
        const invocation = createInvocation(
            { ...createHogExecutionGlobals({ groups: exampleGroups }), inputs: {} },
            { ...exampleHogFunction, team_id: 2 }
        )

        const [sanitized] = sanitizer.sanitizeInvocations([invocation])
        expect(sanitized.state!.globals.person).toBeUndefined()
    })

    it('should not strip person for non-configured teams', () => {
        const sanitizer = createInvocationSanitizer({
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '99',
            ENCRYPTION_SALT_KEYS,
        })
        const invocation = createInvocation(
            { ...createHogExecutionGlobals({ groups: exampleGroups }), inputs: {} },
            { ...exampleHogFunction, team_id: 2 }
        )

        const [sanitized] = sanitizer.sanitizeInvocations([invocation])
        expect(sanitized.state!.globals.person).toBeDefined()
    })

    it('should sanitize results', () => {
        const sanitizer = createInvocationSanitizer({
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
            ENCRYPTION_SALT_KEYS,
        })
        const invocation = createInvocation(
            { ...createHogExecutionGlobals({ groups: exampleGroups }), inputs: {} },
            exampleHogFunction
        )
        const result: CyclotronJobInvocationResult = {
            invocation,
            finished: false,
            error: null,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
            warehouseWebhookPayloads: [],
            messageAssets: [],
            conversionWatchers: [],
        }

        const [sanitized] = sanitizer.sanitizeResults([result])
        expect(sanitized.invocation.state!.globals.groups).toBeUndefined()
    })
})

describe('integration input references', () => {
    const signer = new EncryptedFields(ENCRYPTION_SALT_KEYS)
    const FAKE_SECRETS = ['fake-access-token-value', 'fake-auth-token-value', 'fake-signing-key-value']

    const hogFunction = createHogFunction({
        ...HOG_EXAMPLES.simple_fetch,
        inputs_schema: [
            { key: 'url', type: 'string', required: true },
            { key: 'twilio', type: 'integration', required: true },
            { key: 'channels', type: 'integration_multi', required: true },
        ],
    })

    // The shape `HogInputsService.loadIntegrationInputs` gives a function: config, sensitive_config and the raw token.
    const resolvedInputs = (): Record<string, any> => ({
        url: 'https://example.com',
        twilio: markServerResolvedIntegration({
            $integration_id: 11,
            account_sid: 'AC-fake',
            auth_token: 'fake-auth-token-value',
            access_token: '$$_access_token_placeholder_11_abc',
            access_token_raw: 'fake-access-token-value',
        }),
        channels: [
            markServerResolvedIntegration({
                $integration_id: 12,
                project_id: 'fake-project',
                access_token_raw: 'fake-access-token-value',
            }),
            markServerResolvedIntegration({
                $integration_id: 13,
                bundle_id: 'com.example.app',
                signing_key: 'fake-signing-key-value',
            }),
        ],
    })

    const hogFunctionInvocation = () =>
        createInvocation({ ...createHogExecutionGlobals(), inputs: resolvedInputs() }, hogFunction)

    const pausedWorkflowInvocation = (): CyclotronJobInvocation => ({
        id: 'flow-invocation',
        teamId: 1,
        functionId: 'flow-1',
        queue: 'hogflow',
        queuePriority: 0,
        state: {
            event: createHogExecutionGlobals().event,
            actionStepCount: 1,
            currentAction: {
                id: 'action-1',
                startedAtTimestamp: 0,
                hogFunctionState: {
                    globals: { ...createHogExecutionGlobals(), inputs: resolvedInputs() },
                    timings: [],
                    attempts: 0,
                },
            },
        },
    })

    const serializers: [string, (invocation: CyclotronJobInvocation) => string][] = [
        ['the postgres job state', (invocation) => invocationToV2JobInit(invocation).state!.toString('utf-8')],
        ['the kafka job message', (invocation) => JSON.stringify(serializeInvocation(invocation))],
    ]

    describe.each([
        ['a hog function invocation', hogFunctionInvocation],
        ['a workflow paused in a function step', pausedWorkflowInvocation],
    ])('for %s', (_name, buildInvocation) => {
        it.each(serializers)('keeps every integration secret out of %s', (_serializer, serialize) => {
            const sanitizer = createInvocationSanitizer(
                { CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '', ENCRYPTION_SALT_KEYS },
                { isEnabled: () => true }
            )
            const invocation = buildInvocation()

            const serialized = serialize(sanitizer.sanitizeInvocations([invocation])[0])

            for (const secret of FAKE_SECRETS) {
                expect(serialized).not.toContain(secret)
            }
            const ref = (key: string, id: number) => ({
                $integration_ref: id,
                $integration_ref_sig: signIntegrationRef(signer, invocation.teamId, key, id),
            })
            expect(serialized).toContain(`"twilio":${JSON.stringify(ref('twilio', 11))}`)
            expect(serialized).toContain(`"channels":${JSON.stringify([ref('channels', 12), ref('channels', 13)])}`)
            expect(serialized).toContain('"url":"https://example.com"')
            // The invocation the worker keeps in memory still holds the resolved values.
            expect(JSON.stringify(invocation)).toContain('fake-auth-token-value')
        })

        it('keeps the resolved values while the rollout is off', () => {
            const sanitizer = createInvocationSanitizer(
                { CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '', ENCRYPTION_SALT_KEYS },
                { isEnabled: () => false }
            )

            const serialized = JSON.stringify(sanitizer.sanitizeInvocations([buildInvocation()])[0])

            expect(serialized).toContain('fake-auth-token-value')
            expect(serialized).not.toContain('$integration_ref')
        })
    })

    it('replaces the integrations in queued results too', () => {
        const sanitizer = createInvocationSanitizer(
            { CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '', ENCRYPTION_SALT_KEYS },
            { isEnabled: () => true }
        )
        const result: CyclotronJobInvocationResult = {
            invocation: hogFunctionInvocation(),
            finished: false,
            error: null,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
            warehouseWebhookPayloads: [],
            messageAssets: [],
            conversionWatchers: [],
        }

        const [sanitized] = sanitizer.sanitizeResults([result])

        expect(sanitized.invocation.state!.globals.inputs.twilio).toEqual({
            $integration_ref: 11,
            $integration_ref_sig: signIntegrationRef(signer, result.invocation.teamId, 'twilio', 11),
        })
    })

    describe('inputs the executor can build again', () => {
        const markedInvocation = () => {
            const invocation = hogFunctionInvocation()
            invocation.state.inputsSource = { mapping: { index: 0, fingerprint: 'fake-fingerprint' } }
            return invocation
        }
        const asResult = (invocation: CyclotronJobInvocation): CyclotronJobInvocationResult => ({
            invocation,
            finished: false,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
            warehouseWebhookPayloads: [],
            messageAssets: [],
            conversionWatchers: [],
        })
        const sanitizeBoth = (enabled: boolean, invocation: CyclotronJobInvocation): CyclotronJobInvocation[] => {
            const sanitizer = createInvocationSanitizer(
                { CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '', ENCRYPTION_SALT_KEYS },
                { isEnabled: () => enabled }
            )
            return [
                sanitizer.sanitizeInvocations([invocation])[0],
                sanitizer.sanitizeResults([asResult(invocation)])[0].invocation,
            ]
        }

        it('stores the marker and no inputs, and leaves the invocation in memory as it was', () => {
            const invocation = markedInvocation()

            for (const sanitized of sanitizeBoth(true, invocation)) {
                expect('inputs' in sanitized.state!.globals).toBe(false)
                expect(sanitized.state).toMatchObject({
                    inputsOmitted: true,
                    inputsSource: { mapping: { index: 0, fingerprint: 'fake-fingerprint' } },
                })
                expect(JSON.stringify(sanitized)).not.toContain('https://example.com')
            }
            expect(invocation.state.globals.inputs).toEqual(resolvedInputs())
            expect(invocation.state.inputsOmitted).toBeUndefined()
        })

        it.each([
            ['the rollout is off', false, markedInvocation, 'fake-auth-token-value'],
            ['the invocation has no marker', true, hogFunctionInvocation, '$integration_ref'],
            ['a workflow paused in a function step', true, pausedWorkflowInvocation, '$integration_ref'],
        ])('keeps the inputs when %s', (_name, enabled, buildInvocation, expected) => {
            for (const sanitized of sanitizeBoth(enabled, buildInvocation())) {
                const serialized = JSON.stringify(sanitized)
                expect(serialized).toContain('"url":"https://example.com"')
                expect(serialized).toContain(expected)
                expect(serialized).not.toContain('inputsOmitted')
            }
        })
    })

    it.each([
        ['no integration input', { url: 'https://example.com', body: { a: 1 } }],
        ['an integration input that did not resolve', { url: 'https://example.com', twilio: null, channels: [] }],
        [
            'event data shaped like a resolved integration',
            { url: 'https://example.com', twilio: { $integration_id: 11 }, channels: [{ $integration_id: 12 }] },
        ],
    ])('returns the original invocation when there is %s', (_name, inputs) => {
        const invocation = createInvocation({ ...createHogExecutionGlobals(), inputs }, hogFunction)
        delete invocation.state.globals.groups

        expect(sanitizeInvocationForPersistence(invocation, { integrationRefSigner: signer })).toBe(invocation)
    })
})

describe('transactional send sealing', () => {
    const CDP_SEALED_STATE_KEYS = '00feed0000feed0000feed0000feed00'
    const keys = new EncryptedFields(CDP_SEALED_STATE_KEYS)
    const CODE = 'fake-login-code-482913'
    const send = (event: string): CyclotronJobInvocation => ({
        id: '019a4f3e-7c1d-7000-8000-00000000c0de',
        teamId: 2,
        functionId: 'flow-1',
        queue: 'email',
        queuePriority: 1,
        queueParameters: { type: 'email', html: CODE } as any,
        state: {
            event: { uuid: 'e-1', event, distinct_id: 'user-42', properties: { to: 'ada@example.com' } },
            variables: { code: CODE },
            globals: undefined,
            currentAction: { id: 'email', startedAtTimestamp: 0, hogFunctionState: { vmState: { stack: [CODE] } } },
            acceptedAt: '2026-11-17T10:00:00.000Z',
        },
    })
    const sanitizer = (sealing: boolean) =>
        createInvocationSanitizer(
            {
                CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
                CDP_SEAL_TRANSACTIONAL_EMAIL_STATE: sealing,
                CDP_SEALED_STATE_KEYS,
                ENCRYPTION_SALT_KEYS,
            },
            { isEnabled: () => false }
        )

    it.each([
        ['the postgres job state', (stored: CyclotronJobInvocation) => invocationToV2JobInit(stored).state!],
        ['the kafka job message', (stored: CyclotronJobInvocation) => JSON.stringify(serializeInvocation(stored))],
    ])('keeps a transactional send out of %s and reads it back whole', (name, serialize) => {
        const invocation = send('$transactional_email')

        const bytes = serialize(sanitizer(true).sanitizeInvocations([invocation])[0]).toString()
        const read =
            name === 'the kafka job message'
                ? openSealedState(parseJSON(bytes), invocation, keys)
                : v2JobToInvocation(
                      { ...invocation, queueName: 'email', priority: 1, state: Buffer.from(bytes) } as any,
                      keys
                  )

        expect(bytes).not.toContain(CODE)
        expect(bytes).not.toContain('ada@example.com')
        expect(bytes).toContain('"acceptedAt":"2026-11-17T10:00:00.000Z"')
        expect([read.state, read.queueParameters]).toEqual([invocation.state, invocation.queueParameters])
        expect(openSealedState(parseJSON(bytes), invocation, new EncryptedFields(ENCRYPTION_SALT_KEYS))).toMatchObject({
            stateUnreadable: true,
        })
    })

    it.each([undefined, ',,'])('refuses to start sealing without its own keys (%p)', (CDP_SEALED_STATE_KEYS) => {
        expect(() =>
            createInvocationSanitizer({
                CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
                CDP_SEAL_TRANSACTIONAL_EMAIL_STATE: true,
                CDP_SEALED_STATE_KEYS,
                ENCRYPTION_SALT_KEYS,
            })
        ).toThrow('CDP_SEALED_STATE_KEYS is not set')
    })

    it.each([
        ['the rollout is off', '$transactional_email', false],
        ['a workflow run that is not a transactional send', '$pageview', true],
    ])('stores the content as it is when %s', (_name, event, sealing) => {
        const [stored] = sanitizer(sealing).sanitizeInvocations([send(event)])

        expect(stored.sealed).toBeUndefined()
        expect(JSON.stringify(stored)).toContain(CODE)
    })
})
