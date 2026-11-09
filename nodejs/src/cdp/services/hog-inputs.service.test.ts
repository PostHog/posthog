import '~/tests/helpers/mocks/date.mock'

import { DateTime } from 'luxon'
import { register } from 'prom-client'
import { inspect } from 'util'

import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { configureEventLoopYield, getEventLoopYieldThresholdMs } from '~/common/utils/event-loop-yield'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { HOG_FILTERS_EXAMPLES } from '../_tests/examples'
import { createHogExecutionGlobals, createHogFunction, insertIntegration } from '../_tests/fixtures'
import { compileHog } from '../templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { credentialAuthCounter } from '../utils/credential-auth'
import { deadlineAfter } from '../utils/deadline'
import { EncryptedFields } from '../utils/encryption-utils'
import { HogConfigurationError, classifyHogError } from '../utils/hog-error-classification'
import { replaceIntegrationInputsWithRefs, signIntegrationRef } from '../utils/integration-input-refs'
import { buildHogFunctionInvocations } from '../utils/invocation-utils'
import { LIQUID_RENDER_LIMIT_MS, LiquidRenderBudget } from '../utils/liquid'
import { NATIVE_PUSH_TEMPLATE_ID } from '../utils/push-subscription-utils'
import { HogInputsService, formatHogInput, formatLiquidInput, getAppIdentifierForPush } from './hog-inputs.service'
import { serializeInvocation } from './job-queue/job-queue-kafka'
import { invocationToV2JobInit } from './job-queue/job-queue-postgres-v2'
import { sanitizeInvocationForPersistence } from './job-queue/shared'
import { RecipientTokensService } from './messaging/recipient-tokens.service'

describe('getAppIdentifierForPush', () => {
    it('returns null when no integration inputs are present', () => {
        expect(getAppIdentifierForPush({})).toBeNull()
        expect(getAppIdentifierForPush({ push_provider: { value: null } })).toBeNull()
    })

    it('returns null when integration has no project_id or bundle_id', () => {
        expect(getAppIdentifierForPush({ push_provider: { value: { key_id: 'abc' } } })).toBeNull()
    })

    it('returns project_id from a Firebase integration input', () => {
        const result = getAppIdentifierForPush({
            push_provider: { value: { project_id: 'my-firebase-project', key_id: 'abc' } },
        })
        expect(result).toBe('my-firebase-project')
    })

    it('returns bundle_id from an APNS integration input', () => {
        const result = getAppIdentifierForPush({
            push_provider: { value: { bundle_id: 'com.example.app', key_id: 'abc' } },
        })
        expect(result).toBe('com.example.app')
    })

    it('returns the first app identifier when multiple integrations are present', () => {
        const result = getAppIdentifierForPush({
            firebase_account: { value: { project_id: 'firebase-proj' } },
            apns_account: { value: { bundle_id: 'com.example.app' } },
        })
        expect(result).toBe('firebase-proj')
    })
})

describe('Hog Inputs', () => {
    let hub: Hub
    let team: Team
    let hogInputsService: HogInputsService
    let recipientTokensService: RecipientTokensService
    let integrationId1: number
    let integrationId2: number

    beforeEach(async () => {
        hub = await createHub()
        hub.SITE_URL = 'http://localhost:8000'
        team = (await createTestTeamFixture(hub.postgres)).team
        integrationId1 = team.id
        integrationId2 = team.id + 1

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        await insertIntegration(hub.postgres, team.id, {
            id: integrationId1,
            kind: 'slack',
            config: { team: 'foobar' },
            sensitive_config: {
                access_token: hub.encryptedFields.encrypt('token'),
                not_encrypted: 'not-encrypted',
            },
        })

        await insertIntegration(hub.postgres, team.id, {
            id: integrationId2,
            kind: 'oauth',
            config: { team: 'foobar', access_token: 'token' },
            sensitive_config: {
                not_encrypted: 'not-encrypted',
            },
        })

        recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        hogInputsService = new HogInputsService(hub.integrationManager, recipientTokensService, hub.encryptedFields)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const insertWarehouseIntegration = async (config: unknown): Promise<number> => {
        const id = team.id + 3
        await insertIntegration(hub.postgres, team.id, {
            id,
            kind: 'postgresql' as any,
            config: (typeof config === 'string' ? JSON.stringify(config) : config) as any,
            sensitive_config: { password: hub.encryptedFields.encrypt('secret-password') },
        })
        return id
    }

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

        it('names a missing global in the error and keeps every other VM message out', async () => {
            const globals = createHogExecutionGlobals({ inputs: {} } as any) as any
            // {distinct_id}: GET_GLOBAL on a name the globals do not have.
            const missingGlobal = ['_H', 1, 32, 'distinct_id', 1, 1]
            await expect(formatHogInput(missingGlobal, globals, 'field')).rejects.toThrow(
                'Could not execute bytecode for input field: field: Global variable not found: distinct_id'
            )
            // dateDiff('bogus', 1, 1): the VM quotes its argument, which can be a secret input.
            const quotesArgument = ['_H', 1, 32, 'bogus', 33, 1, 33, 1, 2, 'dateDiff', 3]
            const thrown = await formatHogInput(quotesArgument, globals, 'field').then(
                () => undefined,
                (error) => error
            )
            expect(thrown.message).toMatch(/^Could not execute bytecode for input field: field$/)
            // The kind travels for the classifier; the quoted argument does not, even through a serialized cause chain.
            expect(thrown.cause).toMatchObject({ kind: 'data' })
            expect(inspect(thrown)).not.toContain('bogus')
        })

        const exhaustedBudget = (): LiquidRenderBudget => {
            const budget = new LiquidRenderBudget()
            budget.useTime(Number.MAX_SAFE_INTEGER)
            return budget
        }

        const renderFailures = async (reason: string): Promise<number> => {
            const metric = await register.getSingleMetric('cdp_liquid_render_failures_total')?.get()
            return metric?.values.find((v) => v.labels.reason === reason)?.value ?? 0
        }

        it('exports every render failure reason before the first failure', async () => {
            const metric = await register.getSingleMetric('cdp_liquid_render_failures_total')?.get()
            expect(metric?.values.map((v) => v.labels.reason).sort()).toEqual([
                'contract',
                'data',
                'memory',
                'output',
                'parse_length',
                'time',
            ])
        })

        it.each([
            ['an unsupported filter', '{{ event.event | where_exp: "i", "i" }}', 'contract', 'contract', undefined],
            ['a syntax error', '{% if %}', 'contract', 'contract', undefined],
            // The same template renders for a well-formed URL, so this failure belongs to the event.
            [
                'a malformed URL meeting url_decode',
                '{{ event.properties.url | url_decode }}',
                'data',
                'data',
                undefined,
            ],
            [
                'a template over its memory budget',
                "{% assign s = 'aaaaaaaa' %}{% for i in (1..40) %}{% assign s = s | append: s %}{% endfor %}{{ s | size }}",
                'limit',
                'memory',
                undefined,
            ],
            ['an invocation out of render time', '{{ event.event }}', 'limit', 'time', exhaustedBudget],
        ])(
            'gives a liquid failure from %s a kind, keeps its message and counts it',
            async (_name, template, kind, reason, budget) => {
                const globals = createHogExecutionGlobals({
                    event: { event: '$pageview', properties: { url: '%' } } as any,
                    inputs: {},
                } as any) as any
                const before = await renderFailures(reason)
                let thrown: any
                try {
                    formatLiquidInput(template, globals, 'field', budget?.())
                } catch (error) {
                    thrown = error
                }
                expect(thrown).toBeInstanceOf(Error)
                expect(thrown.message).toBe(thrown.cause.message)
                expect(thrown.cause).toMatchObject({ kind })
                expect(await renderFailures(reason)).toBe(before + 1)
            }
        )

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

        const insertUndecryptableIntegration = async (id: number, teamId = team.id): Promise<void> => {
            await insertIntegration(hub.postgres, teamId, {
                id,
                kind: 'slack',
                sensitive_config: { access_token: new EncryptedFields('f'.repeat(32)).encrypt('token') },
            })
        }

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
                    oauth: { value: integrationId1 },
                },
                inputs_schema: [
                    { key: 'hog_templated', type: 'string', required: true },
                    { key: 'oauth', type: 'integration', required: true },
                ],
            })

            globals = createHogExecutionGlobals()
        })

        it('should template out hog inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.hog_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        const passedDeadline = (): AbortController => {
            const deadline = new AbortController()
            deadline.abort(new DOMException('The verification deadline passed', 'TimeoutError'))
            return deadline
        }

        it.each([
            ['hog', { value: 'x', templating: 'hog' as const, bytecode: ['_H', 1, 32, 'x'] }],
            ['liquid', { value: '{{ event.event }}', templating: 'liquid' as const }],
        ])('renders no %s input once the deadline it was given has passed', async (_templating, input) => {
            const onlyThatInput = createHogFunction({ ...hogFunction, inputs: { only: input }, inputs_schema: [] })

            await expect(
                hogInputsService.buildInputs(onlyThatInput, globals, undefined, undefined, passedDeadline().signal)
            ).rejects.toThrow('The verification deadline passed')
        })

        it.each([
            [
                'it is aborted',
                (): { signal: AbortSignal; pass: () => void } => {
                    const deadline = new AbortController()
                    return {
                        signal: deadline.signal,
                        pass: () =>
                            deadline.abort(new DOMException('The verification deadline passed', 'TimeoutError')),
                    }
                },
            ],
            [
                'the clock passes it before its timer fires',
                (): { signal: AbortSignal; pass: () => void } => ({
                    signal: deadlineAfter(60_000),
                    pass: () => jest.advanceTimersByTime(60_000),
                }),
            ],
        ])(
            'fails the inputs with the deadline error when the deadline passes while a hog input waits for its turn on the event loop because %s',
            async (_how, deadlineFor) => {
                const busyFor = 30_000
                const busy = await compileHog(
                    `while (toUnixTimestampMilli(now()) < event.properties.busy_until) { } return 'done'`
                )
                const onlyHog = createHogFunction({
                    ...hogFunction,
                    inputs: { only: { value: 'x', templating: 'hog', bytecode: busy } },
                    inputs_schema: [],
                })
                const mockedNow = jest.mocked(Date.now)
                const fixedNow = mockedNow()
                const threshold = getEventLoopYieldThresholdMs()
                await new Promise((resolve) => setTimeout(resolve, 5))
                configureEventLoopYield(0)
                jest.useFakeTimers({
                    doNotFake: [
                        'hrtime',
                        'nextTick',
                        'queueMicrotask',
                        'setImmediate',
                        'clearImmediate',
                        'setInterval',
                        'clearInterval',
                        'Date',
                    ],
                })
                const nextTurn = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))
                try {
                    mockedNow.mockImplementation(() => Number(process.hrtime.bigint() / 1_000_000n))
                    const startedAt = Date.now()
                    const deadline = deadlineFor()
                    let outcome: unknown
                    const busyForSeconds = {
                        ...globals,
                        event: {
                            ...globals.event,
                            properties: { ...globals.event.properties, busy_until: startedAt + busyFor },
                        },
                    }
                    void hogInputsService
                        .buildInputs(onlyHog, busyForSeconds, undefined, undefined, deadline.signal)
                        .then(
                            () => (outcome = 'rendered'),
                            (error: unknown) => (outcome = error)
                        )
                    for (let turn = 0; jest.getTimerCount() === 0 && turn < 1000; turn++) {
                        await nextTurn()
                    }
                    expect(outcome).toBeUndefined()

                    deadline.pass()
                    for (let turn = 0; outcome === undefined && turn < 1000; turn++) {
                        jest.runOnlyPendingTimers()
                        await nextTurn()
                    }

                    expect(outcome).toMatchObject({ name: 'TimeoutError' })
                } finally {
                    mockedNow.mockReturnValue(fixedNow)
                    jest.useRealTimers()
                    configureEventLoopYield(threshold)
                }
            }
        )

        it('fails the inputs with the deadline error when the deadline passes while a hog input yields the event loop after its render', async () => {
            const onlyHog = createHogFunction({
                ...hogFunction,
                inputs: { only: { value: 'x', templating: 'hog', bytecode: ['_H', 1, 32, 'x'] } },
                inputs_schema: [],
            })
            const threshold = getEventLoopYieldThresholdMs()
            await new Promise((resolve) => setTimeout(resolve, 5))
            configureEventLoopYield(0)
            jest.useFakeTimers({
                doNotFake: [
                    'hrtime',
                    'nextTick',
                    'queueMicrotask',
                    'setImmediate',
                    'clearImmediate',
                    'setInterval',
                    'clearInterval',
                    'Date',
                ],
            })
            const nextTurn = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))
            const untilAYieldWaits = async (): Promise<void> => {
                for (let turn = 0; jest.getTimerCount() === 0 && turn < 1000; turn++) {
                    await nextTurn()
                }
            }
            try {
                const deadline = new AbortController()
                let outcome: unknown
                void hogInputsService.buildInputs(onlyHog, globals, undefined, undefined, deadline.signal).then(
                    () => (outcome = 'rendered'),
                    (error: unknown) => (outcome = error)
                )
                await untilAYieldWaits()
                jest.runOnlyPendingTimers()
                await untilAYieldWaits()
                expect(outcome).toBeUndefined()

                deadline.abort(new DOMException('The verification deadline passed', 'TimeoutError'))
                for (let turn = 0; outcome === undefined && turn < 1000; turn++) {
                    jest.runOnlyPendingTimers()
                    await nextTurn()
                }

                expect(outcome).toMatchObject({ name: 'TimeoutError' })
            } finally {
                jest.useRealTimers()
                configureEventLoopYield(threshold)
            }
        })

        it('fails every build that shares a deadline with the deadline error when it passes while their hog inputs queue behind another render', async () => {
            const onlyHog = createHogFunction({
                ...hogFunction,
                inputs: { only: { value: 'x', templating: 'hog', bytecode: ['_H', 1, 32, 'x'] } },
                inputs_schema: [],
            })
            const compiledUnder = (contract: string): HogFunctionType =>
                createHogFunction({
                    ...hogFunction,
                    inputs: {
                        only: {
                            value: 'x',
                            templating: 'hog',
                            bytecode: ['_H', 1, 32, 'x'],
                            bytecode_contract: contract,
                        },
                    },
                    inputs_schema: [],
                })
            const threshold = getEventLoopYieldThresholdMs()
            await new Promise((resolve) => setTimeout(resolve, 5))
            configureEventLoopYield(0)
            jest.useFakeTimers({
                doNotFake: [
                    'hrtime',
                    'nextTick',
                    'queueMicrotask',
                    'setImmediate',
                    'clearImmediate',
                    'setInterval',
                    'clearInterval',
                    'Date',
                ],
            })
            const nextTurn = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))
            try {
                let first: unknown
                void hogInputsService.buildInputs(onlyHog, globals).then(
                    () => (first = 'rendered'),
                    (error: unknown) => (first = error)
                )
                for (let turn = 0; jest.getTimerCount() === 0 && turn < 1000; turn++) {
                    await nextTurn()
                }
                const deadline = new AbortController()
                const contracts = ['older', 'newer']
                const queued: unknown[] = contracts.map(() => undefined)
                contracts.forEach((contract, index) => {
                    void hogInputsService
                        .buildInputs(compiledUnder(contract), globals, undefined, undefined, deadline.signal)
                        .then(
                            () => (queued[index] = 'rendered'),
                            (error: unknown) => (queued[index] = error)
                        )
                })
                for (let turn = 0; turn < 20; turn++) {
                    await nextTurn()
                }
                expect(queued).toEqual([undefined, undefined])

                deadline.abort(new DOMException('The verification deadline passed', 'TimeoutError'))
                for (let turn = 0; queued.includes(undefined) && turn < 1000; turn++) {
                    await nextTurn()
                }

                expect(queued.map((outcome) => (outcome as Error).name)).toEqual(['TimeoutError', 'TimeoutError'])
                expect(first).toBeUndefined()
                for (let turn = 0; first === undefined && turn < 1000; turn++) {
                    jest.runOnlyPendingTimers()
                    await nextTurn()
                }
                expect(first).toBe('rendered')
            } finally {
                jest.useRealTimers()
                configureEventLoopYield(threshold)
            }
        })

        it('fails the inputs with the deadline error when the deadline passes while the rest of a hog input queues behind its own first leaf', async () => {
            const leaf = ['_H', 1, 32, 'x']
            const onlyHog = createHogFunction({
                ...hogFunction,
                inputs: { only: { value: 'x', templating: 'hog', bytecode: leaf } },
                inputs_schema: [],
            })
            const manyLeaves = createHogFunction({
                ...hogFunction,
                inputs: { only: { value: 'x', templating: 'hog', bytecode: Array.from({ length: 5 }, () => leaf) } },
                inputs_schema: [],
            })
            const threshold = getEventLoopYieldThresholdMs()
            await new Promise((resolve) => setTimeout(resolve, 5))
            configureEventLoopYield(0)
            jest.useFakeTimers({
                doNotFake: [
                    'hrtime',
                    'nextTick',
                    'queueMicrotask',
                    'setImmediate',
                    'clearImmediate',
                    'setInterval',
                    'clearInterval',
                    'Date',
                ],
            })
            const nextTurn = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))
            try {
                let first: unknown
                void hogInputsService.buildInputs(onlyHog, globals).then(
                    () => (first = 'rendered'),
                    (error: unknown) => (first = error)
                )
                for (let turn = 0; jest.getTimerCount() === 0 && turn < 1000; turn++) {
                    await nextTurn()
                }
                const deadline = new AbortController()
                let queued: unknown
                void hogInputsService.buildInputs(manyLeaves, globals, undefined, undefined, deadline.signal).then(
                    () => (queued = 'rendered'),
                    (error: unknown) => (queued = error)
                )
                for (let turn = 0; turn < 20; turn++) {
                    await nextTurn()
                }
                for (let turn = 0; first === undefined && turn < 1000; turn++) {
                    jest.runOnlyPendingTimers()
                    await nextTurn()
                }
                for (let turn = 0; jest.getTimerCount() === 0 && turn < 1000; turn++) {
                    await nextTurn()
                }
                expect(first).toBe('rendered')
                expect(queued).toBeUndefined()

                deadline.abort(new DOMException('The verification deadline passed', 'TimeoutError'))
                for (let turn = 0; queued === undefined && turn < 1000; turn++) {
                    await nextTurn()
                }

                expect(queued).toMatchObject({ name: 'TimeoutError' })
            } finally {
                for (let turn = 0; jest.getTimerCount() > 0 && turn < 1000; turn++) {
                    jest.runOnlyPendingTimers()
                    await nextTurn()
                }
                jest.useRealTimers()
                configureEventLoopYield(threshold)
            }
        })

        it.each<[string, Record<string, CyclotronInputType>]>([
            ['an input before the last', { next: { value: '{{ event.event }}', templating: 'liquid', order: 1 } }],
            ['the last input', {}],
        ])('fails the inputs once %s carries the clock past the deadline in its render', async (_which, after) => {
            const deadlineMs = 50
            let now = performance.now()
            const clock = jest.spyOn(performance, 'now').mockImplementation(() => now)
            try {
                const deadline = deadlineAfter(deadlineMs)
                const slowThenNext = createHogFunction({
                    ...hogFunction,
                    inputs: {
                        slow: { value: '{{ event.properties.slow }}', templating: 'liquid', order: 0 },
                        ...after,
                    },
                    inputs_schema: [],
                })
                const properties = { ...globals.event.properties }
                Object.defineProperty(properties, 'slow', {
                    enumerable: true,
                    get: () => {
                        now += 2 * deadlineMs
                        return 'slow'
                    },
                })

                await expect(
                    hogInputsService.buildInputs(
                        slowThenNext,
                        { ...globals, event: { ...globals.event, properties } },
                        undefined,
                        undefined,
                        deadline
                    )
                ).rejects.toMatchObject({ name: 'TimeoutError' })
            } finally {
                clock.mockRestore()
            }
        })

        it('stops a liquid input of many leaves within one leaf of the deadline', async () => {
            const deadlineMs = 50
            const leafMs = 2 * deadlineMs
            let now = performance.now()
            const startedAt = now
            const clock = jest.spyOn(performance, 'now').mockImplementation(() => now)
            try {
                const deadline = deadlineAfter(deadlineMs)
                const leaf = '{{ event.properties.slow }}'
                const manyLeaves = createHogFunction({
                    ...hogFunction,
                    inputs: { leaves: { value: { first: leaf, second: leaf, third: leaf }, templating: 'liquid' } },
                    inputs_schema: [],
                })
                const properties = { ...globals.event.properties }
                Object.defineProperty(properties, 'slow', {
                    enumerable: true,
                    get: () => {
                        now += leafMs
                        return 'slow'
                    },
                })

                await expect(
                    hogInputsService.buildInputs(
                        manyLeaves,
                        { ...globals, event: { ...globals.event, properties } },
                        undefined,
                        undefined,
                        deadline
                    )
                ).rejects.toMatchObject({ name: 'TimeoutError' })
                expect(now - startedAt).toBeLessThan(deadlineMs + leafMs)
            } finally {
                clock.mockRestore()
            }
        })

        it.each<[string, number, () => Promise<CyclotronInputType>]>([
            [
                'hog',
                3000,
                async () => ({
                    value: 'busy',
                    templating: 'hog',
                    bytecode: await compileHog(
                        `while (toUnixTimestampMilli(now()) < event.properties.busy_until) { } return 'done'`
                    ),
                }),
            ],
            [
                'liquid',
                LIQUID_RENDER_LIMIT_MS,
                () =>
                    Promise.resolve({
                        value: '{% for a in (1..1000) %}{% for b in (1..1000) %}{% for c in (1..1000) %}x{% endfor %}{% endfor %}{% endfor %}',
                        templating: 'liquid',
                    }),
            ],
        ])(
            'stops a %s render at the deadline rather than at its own longer limit of %d ms',
            async (_templating, ownLimitMs, busyInput) => {
                const deadlineMs = 50
                const onlyBusy = createHogFunction({
                    ...hogFunction,
                    inputs: { busy: await busyInput() },
                    inputs_schema: [],
                })
                let now = 0
                const clock = jest.spyOn(performance, 'now').mockImplementation(() => (now += 0.01))
                const mockedNow = jest.mocked(Date.now)
                const fixedNow = mockedNow()
                mockedNow.mockImplementation(() => Math.floor((now += 0.01)))
                try {
                    const deadline = deadlineAfter(deadlineMs)
                    const busyLong = {
                        ...globals,
                        event: {
                            ...globals.event,
                            properties: { ...globals.event.properties, busy_until: 2 * ownLimitMs },
                        },
                    }

                    await expect(
                        hogInputsService.buildInputs(onlyBusy, busyLong, undefined, undefined, deadline)
                    ).rejects.toMatchObject({ name: 'TimeoutError' })
                    expect(now).toBeLessThan(ownLimitMs / 2)
                } finally {
                    mockedNow.mockReturnValue(fixedNow)
                    clock.mockRestore()
                }
            }
        )

        it('fails a hog render that the deadline cuts short with the deadline error on a clock that reads whole milliseconds', async () => {
            const deadlineMs = 200
            const busy = await compileHog(
                `while (toUnixTimestampMilli(now()) < event.properties.busy_until) { } return 'done'`
            )
            const onlyBusy = createHogFunction({
                ...hogFunction,
                inputs: { busy: { value: 'busy', templating: 'hog', bytecode: busy } },
                inputs_schema: [],
            })
            let now = 0.5
            const clock = jest.spyOn(performance, 'now').mockImplementation(() => now)
            const mockedNow = jest.mocked(Date.now)
            const fixedNow = mockedNow()
            mockedNow.mockImplementation(() => {
                now += 0.001
                return Math.floor(now)
            })
            try {
                const deadline = deadlineAfter(deadlineMs)
                now = 0.9
                const busyLong = {
                    ...globals,
                    event: {
                        ...globals.event,
                        properties: { ...globals.event.properties, busy_until: 10 * deadlineMs },
                    },
                }

                await expect(
                    hogInputsService.buildInputs(onlyBusy, busyLong, undefined, undefined, deadline)
                ).rejects.toMatchObject({ name: 'TimeoutError' })
            } finally {
                mockedNow.mockReturnValue(fixedNow)
                clock.mockRestore()
            }
        })

        it('should template out liquid inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.liquid_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        it('rejects liquid inputs whose leaves together exceed the invocation budget', async () => {
            const leaf = `{% for i in (1..600) %}${'a'.repeat(10_000)}{% endfor %}`
            hogFunction = createHogFunction({
                ...hogFunction,
                inputs: {
                    ...hogFunction.inputs,
                    liquid_object: { value: { first: leaf, second: leaf }, templating: 'liquid' },
                },
            })
            await expect(hogInputsService.buildInputs(hogFunction, globals)).rejects.toThrow(
                'liquid output limit exceeded'
            )
        })

        it('should load integration inputs and replace access tokens with placeholders', async () => {
            hogFunction = createHogFunction({
                ...hogFunction,
                inputs: {
                    hog_templated: hogFunction.inputs!.hog_templated,
                    liquid_templated: hogFunction.inputs!.liquid_templated,
                    oauth: { value: integrationId1 },
                    auth: { value: integrationId2 },
                },
                inputs_schema: [
                    { key: 'hog_templated', type: 'string', required: true },
                    { key: 'oauth', type: 'integration', required: true },
                    { key: 'auth', type: 'integration', required: true },
                ],
            })
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.oauth).toEqual({
                $integration_id: integrationId1,
                access_token: expect.any(String),
                access_token_raw: 'token',
                not_encrypted: 'not-encrypted',
                team: 'foobar',
            })
            expect(inputs.auth).toEqual({
                $integration_id: integrationId2,
                access_token: expect.any(String),
                access_token_raw: 'token',
                not_encrypted: 'not-encrypted',
                team: 'foobar',
            })
            expect(hogInputsService.acceptedAccessTokenPlaceholders(integrationId1)).toContain(
                inputs.oauth.access_token
            )
            expect(hogInputsService.acceptedAccessTokenPlaceholders(integrationId2)).toContain(inputs.auth.access_token)
        })

        it('renders a credential input as a handle and resolves the credential only for the fetch step', async () => {
            hogFunction = createHogFunction({
                ...hogFunction,
                inputs: { oauth: { value: integrationId1 } },
                encrypted_inputs: {
                    api_key: {
                        value: 'sk_secret',
                        bytecode: await compileHog("return 'sk_secret'"),
                        auth: { scheme: 'bearer', origins: ['https://api.example.com'] },
                    } as any,
                },
                inputs_schema: [
                    { key: 'oauth', type: 'integration', required: true, auth: { scheme: 'bearer' } },
                    { key: 'api_key', type: 'string', secret: true, required: true },
                ],
            })

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs).toEqual({
                oauth: { $integration_id: integrationId1, team: 'foobar', $credential: 'oauth' },
                api_key: { $credential: 'api_key' },
            })
            expect(await hogInputsService.resolveCredential(hogFunction, 'oauth')).toEqual({
                credential: {
                    inputKey: 'oauth',
                    declaration: { scheme: 'bearer' },
                    origins: ['https://slack.com'],
                    secret: 'token',
                },
            })
            expect(await hogInputsService.resolveCredential(hogFunction, 'api_key')).toMatchObject({
                credential: { secret: 'sk_secret', origins: ['https://api.example.com'] },
            })
        })

        // Anyone who can edit the function can edit its schema, so the shape a connection resolves to follows its kind.
        it.each([
            {
                trick: 'auth removed from the schema',
                key: 'slack',
                schema: [{ key: 'slack', type: 'integration' }],
                inputs: (id: number) => ({ slack: { value: id } }),
            },
            {
                trick: 'a second input on the same connection',
                key: 'copy',
                schema: [
                    { key: 'slack', type: 'integration', auth: { scheme: 'bearer' } },
                    { key: 'copy', type: 'integration' },
                ],
                inputs: (id: number) => ({ slack: { value: id }, copy: { value: id } }),
            },
            {
                trick: 'an integration_multi input',
                key: 'many',
                schema: [{ key: 'many', type: 'integration_multi' }],
                inputs: (id: number) => ({ many: { value: [id] } }),
            },
        ])('resolves a slack connection reached through $trick by its kind', async ({ key, schema, inputs }) => {
            const legacyResolutions = async (mode: string): Promise<number> =>
                (await credentialAuthCounter.get()).values.find(
                    (v) => v.labels.outcome === 'legacy_integration' && v.labels.mode === mode
                )?.value ?? 0
            const fn = createHogFunction({
                ...hogFunction,
                inputs: inputs(integrationId1),
                inputs_schema: schema as HogFunctionType['inputs_schema'],
            })
            const enforced = new HogInputsService(
                hub.integrationManager,
                recipientTokensService,
                hub.encryptedFields,
                String(team.id)
            )

            const enforcedValue = (await enforced.buildInputs(fn, globals))[key]
            const replacements = await enforced.loadIntegrationInputs(fn)

            const handle = { $integration_id: integrationId1, team: 'foobar' }
            expect(enforcedValue).toEqual(Array.isArray(enforcedValue) ? [handle] : { ...handle, $credential: key })
            expect(JSON.stringify(replacements)).not.toContain('access_token')

            const before = await legacyResolutions('observe')
            const observedValue = (await hogInputsService.buildInputs(fn, globals))[key]

            expect([observedValue].flat()[0]).toMatchObject({ access_token_raw: 'token' })
            expect((await legacyResolutions('observe')) - before).toBe(1)
        })

        it('should coerce string results to booleans for boolean schema fields', async () => {
            hogFunction.inputs = {
                is_enabled: {
                    value: 'true',
                    templating: 'liquid',
                },
            }
            hogFunction.inputs_schema = [{ key: 'is_enabled', type: 'boolean', required: false, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.is_enabled).toBe(true)
        })

        it('should coerce "false" string to false for boolean schema fields', async () => {
            hogFunction.inputs = {
                is_enabled: {
                    value: 'false',
                    templating: 'liquid',
                },
            }
            hogFunction.inputs_schema = [{ key: 'is_enabled', type: 'boolean', required: false, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.is_enabled).toBe(false)
        })

        it.each([
            ['was deleted', (): void => void (hogFunction.inputs!.oauth = { value: 99999999 })],
            ['belongs to a different team', (): void => void (hogFunction.team_id = 100)],
        ])('fails instead of running without the integration when it %s', async (_name, setup) => {
            setup()

            const error = await hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)

            expect(error.message).toContain("The integration for input 'oauth' no longer exists.")
            // Anything but `config` parks the event and blocks DLQ replay on a failure no replay can fix.
            expect(classifyHogError(error, { runtimeContract: 'any' })).toBe('config')
        })

        it('ignores a deleted integration on a mapping this invocation does not use', async () => {
            hogFunction.mappings = [
                { inputs: { slack: { value: 99999999 } }, inputs_schema: [{ key: 'slack', type: 'integration' }] },
            ]

            await expect(hogInputsService.buildInputs(hogFunction, globals)).resolves.toBeDefined()
            await expect(
                hogInputsService.buildInputs(hogFunction, globals, hogFunction.mappings[0].inputs ?? {})
            ).rejects.toThrow("The integration for input 'slack' no longer exists.")
        })

        it('fails a used integration input when the integration cannot be decrypted', async () => {
            const id = 100000000 + team.id
            await insertUndecryptableIntegration(id)
            hogFunction.inputs = { oauth: { value: id } }
            hogFunction.inputs_schema = [{ key: 'oauth', type: 'integration', required: true }]

            const error = await hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)

            expect(error).toBeInstanceOf(HogConfigurationError)
            expect(error.message).toContain('could not be decrypted')
            expect(classifyHogError(error, { runtimeContract: 'any' })).toBe('config')
        })

        it('loads an undecryptable integration on a mapping this invocation does not use', async () => {
            const id = 100000000 + team.id
            await insertUndecryptableIntegration(id)
            hogFunction.mappings = [
                { inputs: { slack: { value: id } }, inputs_schema: [{ key: 'slack', type: 'integration' }] },
            ]

            await expect(hogInputsService.buildInputs(hogFunction, globals)).resolves.toBeDefined()
            const loaded = await hogInputsService.loadIntegrationInputs(hogFunction)
            expect(loaded.slack.value).toEqual({ $integration_id: id })
        })

        it('keeps the other channels of a used integration_multi input but drops the undecryptable secrets', async () => {
            const id = 100000000 + team.id
            await insertUndecryptableIntegration(id)
            hogFunction.inputs = { channels: { value: [integrationId1, id] } }
            hogFunction.inputs_schema = [{ key: 'channels', type: 'integration_multi', required: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.channels).toHaveLength(2)
            expect(inputs.channels[0]).toMatchObject({ $integration_id: integrationId1 })
            expect(inputs.channels[1]).toEqual({ $integration_id: id })
        })

        it.each([
            ['integration', "The integration for input 'connection' no longer exists."],
            ['integration_multi', null],
        ])('does not reveal decrypt failures from another team for %s', async (type, message) => {
            const otherTeam = (await createTestTeamFixture(hub.postgres)).team
            const foreignId = 100000000 + otherTeam.id
            await insertUndecryptableIntegration(foreignId, otherTeam.id)
            hogFunction.inputs = {
                connection: { value: type === 'integration' ? foreignId : [integrationId1, foreignId] },
            }
            hogFunction.inputs_schema = [{ key: 'connection', type: type as any, required: true }]

            const result = await hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)

            if (message) {
                expect(result.message).toContain(message)
            } else {
                expect(result).not.toBeInstanceOf(Error)
            }
            expect(result.message ?? '').not.toContain('could not be decrypted')
        })

        it('should not load a posthog connection', async () => {
            const connectionId = team.id + 2
            await insertIntegration(hub.postgres, team.id, {
                id: connectionId,
                kind: 'posthog',
                sensitive_config: { access_token: hub.encryptedFields.encrypt('connection-token') },
            })
            hogFunction.inputs = { connection: { value: connectionId } }
            hogFunction.inputs_schema = [{ key: 'connection', type: 'integration', required: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.connection).toBeNull()
        })

        it.each([
            ['a marker with a string value', { warehouse_source_type: 'Postgres', host: 'db.example.com' }],
            ['a marker with an empty string', { warehouse_source_type: '', host: 'db.example.com' }],
            ['a marker with a null value', { warehouse_source_type: null, host: 'db.example.com' }],
            ['a config that is a string', 'host=db.example.com'],
            ['a config that is an array', ['db.example.com']],
        ])('blocks an integration with %s', async (_name, config) => {
            const warehouseId = await insertWarehouseIntegration(config)
            hogFunction.inputs = { connection: { value: warehouseId } }
            hogFunction.inputs_schema = [{ key: 'connection', type: 'integration', required: true }]

            const error = await hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)

            expect(error.message).toContain("The integration for input 'connection' can't be used as a function input.")
            expect(classifyHogError(error, { runtimeContract: 'any' })).toBe('config')
            const loaded = await hogInputsService.loadIntegrationInputs(hogFunction)
            expect(loaded.connection.value).toBeNull()
        })

        it.each([
            ['integration', "The integration for input 'connection' no longer exists."],
            ['integration_multi', null],
        ])("treats another team's warehouse row like a missing row for an %s input", async (type, message) => {
            const otherTeam = (await createTestTeamFixture(hub.postgres)).team
            const foreignId = otherTeam.id
            const missingId = foreignId + 1
            await insertIntegration(hub.postgres, otherTeam.id, {
                id: foreignId,
                kind: 'postgresql' as any,
                config: { warehouse_source_type: 'Postgres', host: 'db.example.com' },
                sensitive_config: { password: hub.encryptedFields.encrypt('secret-password') },
            })
            const run = async (id: number): Promise<any> => {
                hogFunction.inputs = { connection: { value: type === 'integration' ? id : [integrationId1, id] } }
                hogFunction.inputs_schema = [{ key: 'connection', type: type as any, required: true }]
                return hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)
            }

            const foreign = await run(foreignId)
            const missing = await run(missingId)

            if (message) {
                expect(missing.message).toContain(message)
                expect(foreign.message).toBe(missing.message)
            } else {
                expect(missing).not.toBeInstanceOf(Error)
                expect(foreign).toEqual(missing)
            }
            expect(foreign.message ?? '').not.toContain("can't be used as a function input")
        })

        it.each([
            ['no marker', { team: 'foobar' }],
            ['a null config', null],
        ])('loads an integration with %s', async (_name, config) => {
            const warehouseId = await insertWarehouseIntegration({ team: 'foobar' })
            if (config === null) {
                const row = (await hub.integrationManager.getMany([warehouseId]))[warehouseId]
                jest.spyOn(hub.integrationManager, 'getMany').mockResolvedValue({
                    [warehouseId]: { ...row!, config: null as any },
                })
            }
            hogFunction.inputs = { connection: { value: warehouseId } }
            hogFunction.inputs_schema = [{ key: 'connection', type: 'integration', required: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.connection).toMatchObject({ $integration_id: warehouseId, password: 'secret-password' })
        })

        it('fails an integration_multi input that holds a marked row', async () => {
            const warehouseId = await insertWarehouseIntegration({ warehouse_source_type: 'Postgres' })
            hogFunction.inputs = { channels: { value: [integrationId1, warehouseId] } }
            hogFunction.inputs_schema = [{ key: 'channels', type: 'integration_multi', required: true }]

            await expect(hogInputsService.buildInputs(hogFunction, globals)).rejects.toThrow(
                "The integration for input 'channels' can't be used as a function input."
            )
        })

        it.each([
            { name: 'a hog function', source: undefined },
            {
                name: 'a workflow email step',
                source: { appSourceId: 'flow-1', instanceId: 'action-1', workflowId: 'flow-1', invocationId: 'run-1' },
            },
        ])('should add unsubscribe url if email input is present for $name', async ({ source }) => {
            hogFunction.inputs = {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{person.properties.email}}' },
                        html: '<div>Manage subscription preferences here <a href="{{unsubscribe_url}}">here</a>Or, click <a href="{{unsubscribe_url_one_click}}">here</a> to immediately unsubscribe from all marketing emails</div>',
                    },
                },
            }

            hogFunction.inputs_schema = [{ key: 'email', type: 'native_email', required: true, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals, undefined, source)
            expect(inputs.email.to.email).toEqual('test@posthog.com')
            const recipient = { team_id: team.id, identifier: 'test@posthog.com' }
            expect(inputs.email.html).toEqual(
                `<div>Manage subscription preferences here <a href="${recipientTokensService.generatePreferencesUrl(recipient, source)}">here</a>Or, click <a href="${recipientTokensService.generateOneClickUnsubscribeUrl(recipient, source)}">here</a> to immediately unsubscribe from all marketing emails</div>`
            )
        })

        it('escapes liquid output only in the email fields that are written into html', async () => {
            const value = '{{ event.properties.feature }}'
            globals.event.properties.feature = `Logs & "Traces" <beta>`
            hogFunction.inputs = {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{person.properties.email}}', name: value },
                        from: { email: 'hey@example.com', name: value },
                        subject: `Welcome to ${value}`,
                        text: `Welcome to ${value}`,
                        preheader: value,
                        html: `<p>${value}</p>`,
                    },
                },
            }
            hogFunction.inputs_schema = [{ key: 'email', type: 'native_email', required: true, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            const raw = `Logs & "Traces" <beta>`
            const escaped = 'Logs &amp; &#34;Traces&#34; &lt;beta&gt;'
            expect(inputs.email).toMatchObject({
                to: { name: raw },
                from: { name: raw },
                subject: `Welcome to ${raw}`,
                text: `Welcome to ${raw}`,
                preheader: escaped,
                html: `<p>${escaped}</p>`,
            })
        })

        it('renders liquid in push notification inputs without html escaping', async () => {
            globals.event.properties.feature = `Logs & "Traces" <beta>`
            hogFunction.template_id = NATIVE_PUSH_TEMPLATE_ID
            hogFunction.inputs = {
                title: { templating: 'liquid', value: 'Try {{ event.properties.feature }}' },
                body: { templating: 'liquid', value: '{{ event.properties.feature }}' },
                data: { templating: 'liquid', value: { url: 'myapp://{{ event.properties.feature }}' } },
            }
            hogFunction.inputs_schema = [
                { key: 'title', type: 'string', required: true },
                { key: 'body', type: 'string', templating: 'liquid' },
                { key: 'data', type: 'dictionary' },
            ]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            const raw = `Logs & "Traces" <beta>`
            expect(inputs).toMatchObject({ title: `Try ${raw}`, body: raw, data: { url: `myapp://${raw}` } })
        })

        it('drops the editor design from a liquid email instead of rendering it', async () => {
            const tag = '{% if event.event == "test" %}Hi{% endif %}'
            hogFunction.inputs = {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{person.properties.email}}' },
                        html: `<p>${tag}</p>`,
                        design: { body: { rows: [{ values: { textJson: JSON.stringify({ text: tag }) } }] } },
                    },
                },
            }
            hogFunction.inputs_schema = [{ key: 'email', type: 'native_email', required: true, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.email.html).toEqual('<p>Hi</p>')
            expect(inputs.email.design).toBeUndefined()
        })

        it('resolves push subscription inputs without a push integration', async () => {
            const hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {
                    push_provider: { value: integrationId1 },
                    push_subscription: { value: 'user-123' },
                },
                inputs_schema: [
                    {
                        key: 'push_provider',
                        type: 'integration',
                    },
                    {
                        key: 'push_subscription',
                        type: 'push_subscription',
                        platform: 'android',
                    },
                ],
            })

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.push_subscription).toBeNull()
        })
    })

    describe('resolveIntegrationRefs', () => {
        let hogFunction: HogFunctionType

        const signedRef = (key: string, id: number, teamId: number = team.id) => ({
            $integration_ref: id,
            $integration_ref_sig: signIntegrationRef(hub.encryptedFields, teamId, key, id),
        })

        const expectNotLoaded = async (fn: HogFunctionType, inputs: Record<string, any>, key: string) => {
            const error = await hogInputsService.resolveIntegrationRefs(fn, inputs).catch((e) => e)

            expect(error).toBeInstanceOf(HogConfigurationError)
            expect(error.message).toBe(
                `The integration for input '${key}' could not be loaded. It may have been deleted. Select a connected integration for this input.`
            )
        }

        beforeEach(() => {
            hogFunction = createHogFunction({
                team_id: team.id,
                inputs: { oauth: { value: integrationId1 }, channels: { value: [integrationId1, integrationId2] } },
                inputs_schema: [
                    { key: 'oauth', type: 'integration', required: true },
                    { key: 'channels', type: 'integration_multi', required: true },
                    { key: 'body', type: 'json', required: false },
                ],
            })
        })

        it('gives the function the same integration values as a fresh build', async () => {
            const built = await hogInputsService.buildInputs(hogFunction, createHogExecutionGlobals())
            const persisted = replaceIntegrationInputsWithRefs(built, (key, id) =>
                signIntegrationRef(hub.encryptedFields, team.id, key, id)
            )
            expect(JSON.stringify(persisted)).not.toContain('token')

            const resolved = await hogInputsService.resolveIntegrationRefs(hogFunction, persisted)

            expect(resolved).toEqual(built)
            expect(resolved.oauth.access_token_raw).toBe('token')
        })

        it('keeps the secrets out of the persisted job when built through the real enqueue path', async () => {
            const { invocations } = await buildHogFunctionInvocations(
                hogInputsService,
                [{ ...hogFunction, ...HOG_FILTERS_EXAMPLES.no_filters }],
                createHogExecutionGlobals()
            )
            expect(invocations).toHaveLength(1)
            expect(invocations[0].state.globals.inputs.oauth.access_token_raw).toBe('token')

            const sanitized = sanitizeInvocationForPersistence(invocations[0], {
                integrationRefSigner: hub.encryptedFields,
            })

            for (const serialized of [
                invocationToV2JobInit(sanitized).state!.toString('utf-8'),
                JSON.stringify(serializeInvocation(sanitized)),
            ]) {
                expect(serialized).toContain('$integration_ref_sig')
                expect(serialized).not.toContain('token')
            }
        })

        it('passes the resolved values of a job queued before references through unchanged', async () => {
            const built = await hogInputsService.buildInputs(hogFunction, createHogExecutionGlobals())

            await expect(hogInputsService.resolveIntegrationRefs(hogFunction, built)).resolves.toBe(built)
        })

        it.each([
            ['integration', 'oauth', (ref: any) => ref],
            ['integration_multi', 'channels', (ref: any) => [ref]],
        ])('fails an %s reference when the integration cannot be decrypted', async (_type, key, wrap) => {
            const id = 100000000 + team.id
            await insertIntegration(hub.postgres, team.id, {
                id,
                kind: 'slack',
                sensitive_config: { access_token: new EncryptedFields('f'.repeat(32)).encrypt('token') },
            })
            hogFunction.inputs = { [key]: { value: key === 'oauth' ? id : [id] } }

            const error = await hogInputsService
                .resolveIntegrationRefs(hogFunction, { [key]: wrap(signedRef(key, id)) })
                .catch((e) => e)

            expect(error).toBeInstanceOf(HogConfigurationError)
            expect(error.message).toContain('could not be decrypted')
            expect(error.message).toContain(key)
        })

        it('does not resolve a reference in an input that is not an integration input', async () => {
            const inputs = { body: signedRef('body', integrationId1) }

            await expect(hogInputsService.resolveIntegrationRefs(hogFunction, inputs)).resolves.toBe(inputs)
        })

        describe('when one mapping selects an integration under a key that another mapping fills from the event', () => {
            let mappedFunction: HogFunctionType

            beforeEach(() => {
                mappedFunction = createHogFunction({
                    team_id: team.id,
                    mappings: [
                        {
                            inputs_schema: [{ key: 'payload', type: 'integration', required: true }],
                            inputs: { payload: { value: integrationId1 } },
                        },
                        {
                            inputs_schema: [{ key: 'payload', type: 'json', required: true }],
                            inputs: { payload: { value: '{event.properties.payload}', templating: 'liquid' } },
                        },
                    ],
                })
            })

            it('fails and does not load an unsigned reference that the event supplies', async () => {
                const getMany = jest.spyOn(hub.integrationManager, 'getMany')

                await expectNotLoaded(mappedFunction, { payload: { $integration_ref: integrationId1 } }, 'payload')
                expect(getMany).not.toHaveBeenCalledWith(expect.arrayContaining([integrationId1]))
            })

            it('resolves the reference that the server signed', async () => {
                const resolved = await hogInputsService.resolveIntegrationRefs(mappedFunction, {
                    payload: signedRef('payload', integrationId1),
                })

                expect(resolved.payload.access_token_raw).toBe('token')
            })
        })

        it.each([
            ['an unsigned reference', 'oauth', () => Promise.resolve({ $integration_ref: integrationId1 })],
            [
                'a reference with a made-up signature',
                'oauth',
                () => Promise.resolve({ $integration_ref: integrationId1, $integration_ref_sig: 'a'.repeat(64) }),
            ],
            [
                'a reference signed for another team',
                'oauth',
                () => Promise.resolve(signedRef('oauth', integrationId1, team.id + 1000)),
            ],
            [
                'a reference signed for another input key',
                'oauth',
                () => Promise.resolve(signedRef('channels', integrationId1)),
            ],
            [
                'a reference signed for another integration',
                'channels',
                () =>
                    Promise.resolve([
                        {
                            $integration_ref: integrationId1,
                            $integration_ref_sig: signedRef('channels', integrationId2).$integration_ref_sig,
                        },
                    ]),
            ],
            ['a deleted integration', 'oauth', () => Promise.resolve(signedRef('oauth', team.id + 50))],
            [
                'a deleted integration_multi item',
                'channels',
                () => Promise.resolve([signedRef('channels', team.id + 50)]),
            ],
            [
                'a team integration that the function is not configured with',
                'oauth',
                () => Promise.resolve(signedRef('oauth', integrationId2)),
            ],
            [
                "another team's integration",
                'oauth',
                async () => {
                    const otherTeam = (await createTestTeamFixture(hub.postgres)).team
                    const foreign = await insertIntegration(hub.postgres, otherTeam.id, {
                        kind: 'slack',
                        sensitive_config: { access_token: hub.encryptedFields.encrypt('fake-foreign-token') },
                    })
                    return signedRef('oauth', foreign.id)
                },
            ],
            [
                'a posthog connection',
                'oauth',
                async () => {
                    const connection = await insertIntegration(hub.postgres, team.id, {
                        kind: 'posthog',
                        sensitive_config: { access_token: hub.encryptedFields.encrypt('fake-connection-token') },
                    })
                    return signedRef('oauth', connection.id)
                },
            ],
        ])('fails with a clear error for %s', async (_name, key, buildRef) => {
            await expectNotLoaded(hogFunction, { [key]: await buildRef() }, key)
        })
    })
})
