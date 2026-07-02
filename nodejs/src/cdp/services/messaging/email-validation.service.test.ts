import { RedisV2 } from '~/common/redis/redis-v2'

import { CyclotronJobInvocationHogFunction } from '../../types'
import { EmailValidationService } from './email-validation.service'

const mockResolveMx = jest.fn()
const mockResolve4 = jest.fn()
const mockResolve6 = jest.fn()

jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: mockResolveMx,
        resolve4: mockResolve4,
        resolve6: mockResolve6,
    })),
}))

const dnsError = (code: string): NodeJS.ErrnoException => Object.assign(new Error(code), { code })

const emailInvocation = (email: unknown, teamId = 2): CyclotronJobInvocationHogFunction =>
    ({
        teamId,
        id: 'inv-1',
        functionId: 'flow-1',
        state: { actionId: 'act-1', globals: { inputs: { email: { to: { email } } } } },
    }) as any

const emailAction = { type: 'function_email', id: 'act-1' } as any

describe('EmailValidationService', () => {
    let service: EmailValidationService

    beforeEach(() => {
        jest.clearAllMocks()
        // Default to a healthy domain so tests only override what they exercise.
        mockResolveMx.mockResolvedValue([{ exchange: 'mx.example.com', priority: 10 }])
        mockResolve4.mockResolvedValue(['1.2.3.4'])
        mockResolve6.mockResolvedValue([])
        service = new EmailValidationService({ CDP_EMAIL_MX_VALIDATION_TEAMS: '2' }, null)
    })

    describe('gating', () => {
        it('does not validate (returns null, no DNS) for non-email actions', async () => {
            const reason = await service.getSkipReason(emailInvocation('x@dead.invalid'), {
                type: 'function_sms',
                id: 'act-1',
            } as any)
            expect(reason).toBeNull()
            expect(mockResolveMx).not.toHaveBeenCalled()
        })

        it.each([
            ['gated team', 2, false],
            ['ungated team', 3, true],
        ])('%s: skips validation only when team is not gated', async (_label, teamId, expectNull) => {
            mockResolveMx.mockRejectedValue(dnsError('ENOTFOUND'))
            mockResolve4.mockRejectedValue(dnsError('ENOTFOUND'))
            mockResolve6.mockRejectedValue(dnsError('ENOTFOUND'))

            const reason = await service.getSkipReason(emailInvocation('x@dead.invalid', teamId), emailAction)

            if (expectNull) {
                expect(reason).toBeNull()
                expect(mockResolveMx).not.toHaveBeenCalled()
            } else {
                expect(reason).toContain('no reachable mail servers')
            }
        })

        it('validates all teams when configured with "*"', async () => {
            const wildcard = new EmailValidationService({ CDP_EMAIL_MX_VALIDATION_TEAMS: '*' }, null)
            mockResolveMx.mockRejectedValue(dnsError('ENOTFOUND'))
            mockResolve4.mockRejectedValue(dnsError('ENOTFOUND'))
            mockResolve6.mockRejectedValue(dnsError('ENOTFOUND'))

            const reason = await wildcard.getSkipReason(emailInvocation('x@dead.invalid', 999), emailAction)
            expect(reason).toContain('no reachable mail servers')
        })
    })

    describe('syntax validation', () => {
        it.each([
            ['missing @', 'not-an-email'],
            ['empty local part', '@example.com'],
            ['no domain dot', 'user@localhost'],
            ['whitespace', 'user @example.com'],
            ['double @', 'a@b@example.com'],
        ])('blocks %s without a DNS lookup', async (_label, email) => {
            const reason = await service.getSkipReason(emailInvocation(email), emailAction)
            expect(reason).toContain('not a valid email address')
            expect(mockResolveMx).not.toHaveBeenCalled()
        })

        it.each([
            ['missing recipient', undefined],
            ['empty string', ''],
            ['non-string', 12345],
        ])('leaves %s for the existing send path (returns null)', async (_label, email) => {
            const reason = await service.getSkipReason(emailInvocation(email), emailAction)
            expect(reason).toBeNull()
            expect(mockResolveMx).not.toHaveBeenCalled()
        })
    })

    describe('domain deliverability', () => {
        it('allows a domain with MX records', async () => {
            mockResolveMx.mockResolvedValue([{ exchange: 'aspmx.l.google.com', priority: 1 }])
            expect(await service.getSkipReason(emailInvocation('user@gmail.com'), emailAction)).toBeNull()
        })

        it('allows a domain with no MX but an A record (RFC 5321 implicit MX)', async () => {
            mockResolveMx.mockRejectedValue(dnsError('ENODATA'))
            mockResolve4.mockResolvedValue(['93.184.216.34'])
            expect(await service.getSkipReason(emailInvocation('user@example.com'), emailAction)).toBeNull()
        })

        it('allows a domain with no MX or A but an AAAA record', async () => {
            mockResolveMx.mockRejectedValue(dnsError('ENODATA'))
            mockResolve4.mockRejectedValue(dnsError('ENODATA'))
            mockResolve6.mockResolvedValue(['2606:2800:220:1:248:1893:25c8:1946'])
            expect(await service.getSkipReason(emailInvocation('user@example.com'), emailAction)).toBeNull()
        })

        it('blocks a domain with no MX and no address records', async () => {
            mockResolveMx.mockRejectedValue(dnsError('ENODATA'))
            mockResolve4.mockRejectedValue(dnsError('ENODATA'))
            mockResolve6.mockRejectedValue(dnsError('ENODATA'))
            expect(await service.getSkipReason(emailInvocation('user@example.com'), emailAction)).toContain(
                'no reachable mail servers'
            )
        })

        it('blocks a non-existent domain (NXDOMAIN)', async () => {
            mockResolveMx.mockRejectedValue(dnsError('ENOTFOUND'))
            mockResolve4.mockRejectedValue(dnsError('ENOTFOUND'))
            mockResolve6.mockRejectedValue(dnsError('ENOTFOUND'))
            expect(await service.getSkipReason(emailInvocation('user@does-not-exist.invalid'), emailAction)).toContain(
                'no reachable mail servers'
            )
        })

        it('blocks a domain that publishes a null MX (RFC 7505) without an A-record fallback', async () => {
            mockResolveMx.mockResolvedValue([{ exchange: '', priority: 0 }])
            expect(await service.getSkipReason(emailInvocation('user@no-mail.example'), emailAction)).toContain(
                'no reachable mail servers'
            )
            expect(mockResolve4).not.toHaveBeenCalled()
        })
    })

    describe('fail-open on transient DNS errors', () => {
        it.each([['ESERVFAIL'], ['ETIMEOUT'], ['EREFUSED'], ['ECONNREFUSED']])(
            'allows the send when the MX lookup fails with %s',
            async (code) => {
                mockResolveMx.mockRejectedValue(dnsError(code))
                expect(await service.getSkipReason(emailInvocation('user@flaky.example'), emailAction)).toBeNull()
            }
        )

        it('allows the send when the A-record fallback lookup is transiently unavailable', async () => {
            mockResolveMx.mockRejectedValue(dnsError('ENODATA'))
            mockResolve4.mockRejectedValue(dnsError('ESERVFAIL'))
            expect(await service.getSkipReason(emailInvocation('user@flaky.example'), emailAction)).toBeNull()
        })

        it('does not cache a transient failure (retries DNS on the next send)', async () => {
            mockResolveMx.mockRejectedValueOnce(dnsError('ETIMEOUT'))
            expect(await service.getSkipReason(emailInvocation('user@flaky.example'), emailAction)).toBeNull()

            // Domain recovered — a healthy MX response should now be observed, not a frozen "allow".
            mockResolveMx.mockResolvedValue([{ exchange: 'mx.flaky.example', priority: 10 }])
            expect(await service.getSkipReason(emailInvocation('user@flaky.example'), emailAction)).toBeNull()
            expect(mockResolveMx).toHaveBeenCalledTimes(2)
        })
    })

    describe('per-domain caching', () => {
        it('resolves each domain once and serves repeats from the in-process cache', async () => {
            mockResolveMx.mockResolvedValue([{ exchange: 'mx.example.com', priority: 10 }])
            for (let i = 0; i < 5; i++) {
                await service.getSkipReason(emailInvocation(`user${i}@example.com`), emailAction)
            }
            expect(mockResolveMx).toHaveBeenCalledTimes(1)
        })

        it('coalesces concurrent lookups for the same domain into a single DNS query', async () => {
            let resolveLookup: (records: unknown[]) => void = () => {}
            mockResolveMx.mockReturnValue(new Promise((resolve) => (resolveLookup = resolve)))

            const inFlight = Promise.all(
                Array.from({ length: 50 }, (_, i) =>
                    service.getSkipReason(emailInvocation(`user${i}@example.com`), emailAction)
                )
            )
            resolveLookup([{ exchange: 'mx.example.com', priority: 10 }])
            const reasons = await inFlight

            expect(mockResolveMx).toHaveBeenCalledTimes(1)
            expect(reasons.every((r) => r === null)).toBe(true)
        })

        it('honors a Redis-cached verdict without hitting DNS', async () => {
            const redis: RedisV2 = {
                useClient: jest.fn().mockResolvedValue('0'), // '0' = domain previously found undeliverable
                usePipeline: jest.fn(),
            }
            const withRedis = new EmailValidationService({ CDP_EMAIL_MX_VALIDATION_TEAMS: '2' }, redis)

            const reason = await withRedis.getSkipReason(emailInvocation('user@known-dead.example'), emailAction)
            expect(reason).toContain('no reachable mail servers')
            expect(mockResolveMx).not.toHaveBeenCalled()
        })
    })
})
