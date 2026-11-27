import { Registry, register } from 'prom-client'

import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocation } from '~/cdp/types'

import { settleBeforeAbortEvenWhileCredentialsStall } from './attachment-store'
import {
    Admission,
    AttachmentsNotAdmittedError,
    InFlightLimits,
    InFlightRegistry,
    MachineMemory,
    deferralDelayMs,
    estimateSend,
    filesOf,
    inFlightLimitsFor,
    requireAdmission,
} from './in-flight-registry'

const MIB = 1024 * 1024
const GIB = 1024 * MIB

const oneFileOf = (sizeBytes: number, sha256 = 'a'.repeat(64)): EmailAttachmentMetadata[] => [
    { sha256, filename: 'report.pdf', sizeBytes },
]

const pending = (): { promise: Promise<void>; resolve: () => void } => {
    let resolve!: () => void
    const promise = new Promise<void>((done) => (resolve = done))
    return { promise, resolve }
}

describe('InFlightRegistry', () => {
    const roomFor = (sends: number, fileBytes: number): InFlightLimits => ({
        budgetBytes: sends * estimateSend(fileBytes).reservedBytes,
        heapLimitBytes: 64 * GIB,
        maxInFlight: 100,
    })

    it.each([
        ['the in-flight cap is reached', { ...roomFor(5, MIB), maxInFlight: 1 }, () => 0, 'at_cap'],
        ['the reservation would pass the budget', roomFor(1, MIB), () => 0, 'over_budget'],
        [
            'the heap share would pass the heap limit minus the heap in use',
            { ...roomFor(5, MIB), heapLimitBytes: 2 * estimateSend(MIB).heapBytes },
            () => estimateSend(MIB).heapBytes / 2,
            'over_heap',
        ],
    ])('defers a second send when %s, and admits it once the first ends', async (_, limits, heapUsed, reason) => {
        const registry = new InFlightRegistry(limits, heapUsed)
        const first = pending()

        const started = registry.tryStart(oneFileOf(MIB), () => first.promise)
        expect(registry.tryStart(oneFileOf(MIB), () => Promise.resolve())).toEqual({ deferred: reason })
        first.resolve()
        await (started as { started: Promise<void> }).started

        expect(registry.tryStart(oneFileOf(MIB), () => Promise.resolve())).toHaveProperty('started')
    })

    it('serves every deferral reason at zero on the first scrape after the module loads', async () => {
        let registry: Registry | undefined
        jest.isolateModules(() => {
            registry = require('prom-client').register
            require('./in-flight-registry')
        })

        const scrape = await registry!.metrics()
        const samples = scrape
            .split('\n')
            .filter((line) => line.startsWith('cdp_email_attachments_deferral_tokens_total{'))
        expect(samples.sort()).toEqual(
            ['at_cap', 'over_budget', 'over_heap', 'refused'].map(
                (reason) => `cdp_email_attachments_deferral_tokens_total{reason="${reason}"} 0`
            )
        )
    })

    it('defers every send when the worker refused sends with files', () => {
        expect(new InFlightRegistry(null).tryStart(oneFileOf(1), () => Promise.resolve())).toEqual({
            deferred: 'refused',
        })
    })

    it.each([
        [
            'its deadline passed',
            (deadline: AbortController, call: Promise<void>): Promise<unknown> => {
                const loading = settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, call)
                deadline.abort(new Error('deadline'))
                return loading
            },
        ],
        [
            'another file of the send failed',
            (deadline: AbortController, call: Promise<void>): Promise<unknown> =>
                Promise.all([
                    settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, call),
                    settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, Promise.reject(new Error('missing'))),
                ]),
        ],
    ])(
        'keeps the reservation of a send that stopped waiting because %s, until the call settles',
        async (_, abandon) => {
            const registry = new InFlightRegistry(roomFor(1, MIB))
            const download = pending()

            const { started } = registry.tryStart(oneFileOf(MIB), () =>
                abandon(new AbortController(), download.promise).catch(() => undefined)
            ) as { started: Promise<unknown> }
            await started
            expect(registry.tryStart(oneFileOf(MIB), () => Promise.resolve())).toEqual({ deferred: 'over_budget' })
            download.resolve()
            await new Promise(setImmediate)
            expect(registry.tryStart(oneFileOf(MIB), () => Promise.resolve())).toHaveProperty('started')
        }
    )

    describe('requireAdmission', () => {
        const unadmittedLoads = async (reason: string): Promise<number> =>
            (await register.getSingleMetric('cdp_email_attachments_unadmitted_loads_total')!.get()).values.find(
                (sample) => sample.labels.reason === reason
            )?.value ?? 0

        const admissionHeldBy = async (
            files: EmailAttachmentMetadata[],
            during: (admission: Admission) => void = () => undefined
        ): Promise<Admission> => {
            const { started } = new InFlightRegistry(roomFor(1, 4 * MIB)).tryStart(files, () => {
                const admission = requireAdmission(files)
                during(admission)
                return Promise.resolve(admission)
            }) as { started: Promise<Admission> }
            return await started
        }

        it('gives a send the admission for exactly the files it was admitted with', async () => {
            const files = [...oneFileOf(MIB), ...oneFileOf(2 * MIB, 'b'.repeat(64))]

            expect((await admissionHeldBy(files)).files).toEqual(files)
        })

        const changedAfterAdmission = (edit: Partial<EmailAttachmentMetadata>) => (): Promise<Admission> => {
            const files = oneFileOf(MIB)
            return admissionHeldBy(files, () => {
                Object.assign(files[0], edit)
                requireAdmission(files)
            })
        }

        it.each([
            ['outside any send', 'outside_any_admission', () => requireAdmission(oneFileOf(MIB))],
            [
                'for files other than the admitted ones',
                'other_files',
                () => admissionHeldBy(oneFileOf(MIB), () => requireAdmission(oneFileOf(MIB + 1))),
            ],
            [
                'for the admitted files and one more',
                'other_files',
                () => {
                    const files = oneFileOf(MIB)
                    return admissionHeldBy(files, () => requireAdmission([...files, ...oneFileOf(MIB)]))
                },
            ],
            [
                'for files the caller rehashed after their admission',
                'other_files',
                changedAfterAdmission({ sha256: 'f'.repeat(64) }),
            ],
            [
                'for files the caller resized after their admission',
                'other_files',
                changedAfterAdmission({ sizeBytes: 64 * MIB }),
            ],
            [
                'for files the caller renamed after their admission',
                'other_files',
                changedAfterAdmission({ filename: 'other.pdf' }),
            ],
            [
                'for files the caller retyped after their admission',
                'other_files',
                changedAfterAdmission({ contentType: 'text/html' }),
            ],
            [
                'for files the caller inlined after their admission',
                'other_files',
                changedAfterAdmission({ contentId: 'logo' }),
            ],
            [
                'once the admitted send ended',
                'released',
                async () => {
                    let loadAfterTheSend!: Promise<Admission>
                    await admissionHeldBy(oneFileOf(MIB), () => {
                        loadAfterTheSend = new Promise(setImmediate).then(() => requireAdmission(oneFileOf(MIB)))
                    })
                    return await loadAfterTheSend
                },
            ],
        ])('refuses and counts a load %s', async (_, reason, load) => {
            const before = await unadmittedLoads(reason)

            await expect(Promise.resolve().then(load)).rejects.toThrow(AttachmentsNotAdmittedError)
            expect(await unadmittedLoads(reason)).toBe(before + 1)
        })
    })
})

describe('filesOf', () => {
    const queued = oneFileOf(MIB, 'q'.repeat(64))
    const saved = oneFileOf(2 * MIB, 's'.repeat(64))
    const jobWith = (queueParameters: unknown, send: unknown): CyclotronJobInvocation =>
        ({ queueParameters, state: { send } }) as unknown as CyclotronJobInvocation

    it.each([
        [
            'the queued email files over a saved send that disagrees',
            jobWith({ type: 'email', attachments: queued }, { attachments: saved }),
            queued,
        ],
        [
            'no files when the queued email has none, whatever the saved send holds',
            jobWith({ type: 'email' }, { attachments: saved }),
            null,
        ],
        ['the saved send files when nothing is queued', jobWith(undefined, { attachments: saved }), saved],
        ['no files for an empty list', jobWith({ type: 'email', attachments: [] }, undefined), null],
    ])('reads %s', (_, job, files) => {
        expect(filesOf(job)).toEqual(files)
    })
})

describe('inFlightLimitsFor', () => {
    const settings = {
        memoryFraction: 0.5,
        maxInFlight: 4,
        heartbeatIntervalMs: 10_000,
        attachmentStoreBucket: 'files',
    }
    const machine = (overrides: Partial<MachineMemory> = {}): MachineMemory => ({
        constrainedBytes: 4 * GIB,
        totalBytes: 64 * GIB,
        heapLimitBytes: 4 * GIB,
        ...overrides,
    })

    it.each([
        ['the container limit', machine(), 0.5 * (4 * GIB - 512 * MIB)],
        [
            'the machine memory when Node reports no limit as 0',
            machine({ constrainedBytes: 0 }),
            0.5 * (64 * GIB - 512 * MIB),
        ],
        [
            'the machine memory when Node reports no limit as a value past it',
            machine({ constrainedBytes: 2 ** 64 }),
            0.5 * (64 * GIB - 512 * MIB),
        ],
    ])('sizes the budget from %s', (_, memory, budgetBytes) => {
        expect(inFlightLimitsFor(settings, memory)).toEqual({
            limits: { budgetBytes, heapLimitBytes: 4 * GIB, maxInFlight: 4 },
        })
    })

    it.each([
        ['the heartbeat is off', { ...settings, heartbeatIntervalMs: 0 }, machine(), 'heartbeat is off'],
        ['the budget cannot hold one message', settings, machine({ constrainedBytes: 768 * MIB }), 'memory budget'],
        ['the heap cannot hold one message', settings, machine({ heapLimitBytes: 64 * MIB }), 'heap limit'],
        ['the cap is zero', { ...settings, maxInFlight: 0 }, machine(), 'cap'],
        ['no attachment store is set', { ...settings, attachmentStoreBucket: '' }, machine(), 'attachment store'],
    ])('refuses sends with files when %s', (_, given, memory, reason) => {
        expect(inFlightLimitsFor(given, memory)).toEqual({ refusal: expect.stringContaining(reason) })
    })
})

describe('deferralDelayMs', () => {
    it.each([
        [0, 0, 5_000],
        [0, 1, 5_000],
        [1, 0, 5_000],
        [1, 1, 10_000],
        [3, 0, 20_000],
        [3, 1, 40_000],
        [10, 0, 60_000],
        [10, 1, 120_000],
    ])(
        'waits between half and all of a doubling delay after %i deferrals (random %d): %i ms',
        (earlier, random, ms) => {
            expect(deferralDelayMs(earlier, () => random)).toBe(ms)
        }
    )
})
