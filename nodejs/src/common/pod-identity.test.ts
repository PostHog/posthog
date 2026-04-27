import { assembleKafkaClientId, deriveKafkaClientRack, getPodName, isAutoDeriveClientIdEnabled } from './pod-identity'

describe('pod-identity', () => {
    let consoleWarnSpy: jest.SpyInstance
    const originalEnv = { ...process.env }

    beforeEach(() => {
        consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
        consoleWarnSpy.mockRestore()
        process.env = { ...originalEnv }
    })

    describe('deriveKafkaClientRack', () => {
        it.each([
            ['ip-10-20-99-1', 'use1-az6'],
            ['ip-10-21-99-1', 'use1-az1'],
            ['ip-10-22-99-1', 'use1-az2'],
            ['ip-10-30-99-1', 'use1-az2'],
            ['ip-10-31-99-1', 'use1-az4'],
            ['ip-10-32-99-1', 'use1-az6'],
            ['ip-10-40-99-1', 'euc1-az2'],
            ['ip-10-41-99-1', 'euc1-az3'],
            ['ip-10-42-99-1', 'euc1-az1'],
            ['ip-10-22-99-1.ec2.internal', 'use1-az2'],
        ])('derives rack from %s as %s', (nodeName, expected) => {
            expect(deriveKafkaClientRack(nodeName)).toEqual(expected)
            expect(consoleWarnSpy).not.toHaveBeenCalled()
        })

        it('returns undefined and warns when nodeName is undefined', () => {
            expect(deriveKafkaClientRack(undefined)).toBeUndefined()
            expect(consoleWarnSpy).toHaveBeenCalledTimes(1)
            expect(consoleWarnSpy.mock.calls[0][0]).toContain('K8S_NODE_NAME is not set')
        })

        it('returns undefined and warns when nodeName is empty string', () => {
            expect(deriveKafkaClientRack('')).toBeUndefined()
            expect(consoleWarnSpy).toHaveBeenCalledTimes(1)
        })

        it.each(['no-octets-here', 'ip', 'ip-10', 'singleword'])(
            'returns undefined and warns for malformed nodeName %s',
            (nodeName) => {
                expect(deriveKafkaClientRack(nodeName)).toBeUndefined()
                expect(consoleWarnSpy).toHaveBeenCalledTimes(1)
            }
        )

        it('returns undefined and warns for unknown octet', () => {
            expect(deriveKafkaClientRack('ip-10-99-99-1')).toBeUndefined()
            expect(consoleWarnSpy).toHaveBeenCalledTimes(1)
            expect(consoleWarnSpy.mock.calls[0][0]).toContain('unknown second octet "99"')
        })
    })

    describe('getPodName', () => {
        it('prefers POD_NAME', () => {
            process.env.POD_NAME = 'my-pod-1'
            process.env.HOSTNAME = 'host-fallback'
            expect(getPodName()).toEqual('my-pod-1')
        })

        it('falls back to HOSTNAME when POD_NAME is unset', () => {
            delete process.env.POD_NAME
            process.env.HOSTNAME = 'host-fallback'
            expect(getPodName()).toEqual('host-fallback')
        })

        it('falls back to os.hostname when both env vars are unset', () => {
            delete process.env.POD_NAME
            delete process.env.HOSTNAME
            expect(getPodName()).toBeTruthy()
        })
    })

    describe('assembleKafkaClientId', () => {
        const podName = 'my-pod-1'

        it('renders just the pod name when no per-target env vars are set', () => {
            expect(assembleKafkaClientId('CONSUMER', { rack: 'use1-az2', podName })).toEqual('my-pod-1')
        })

        it('emits prefix_az=rack when prefix env is set and rack is available', () => {
            process.env.KAFKA_CONSUMER_CLIENT_ID_PREFIX = 'ws'
            expect(assembleKafkaClientId('CONSUMER', { rack: 'use1-az2', podName })).toEqual('ws_az=use1-az2,my-pod-1')
        })

        it('omits the rack segment when rack is undefined even if prefix is set', () => {
            process.env.KAFKA_CONSUMER_CLIENT_ID_PREFIX = 'ws'
            expect(assembleKafkaClientId('CONSUMER', { rack: undefined, podName })).toEqual('my-pod-1')
        })

        it('inserts extra between rack and pod name', () => {
            process.env.KAFKA_MONITORING_PRODUCER_CLIENT_ID_PREFIX = 'ws'
            process.env.KAFKA_MONITORING_PRODUCER_CLIENT_ID_EXTRA = 'ws_proxy_target=proxy-produce'
            expect(assembleKafkaClientId('MONITORING_PRODUCER', { rack: 'use1-az2', podName })).toEqual(
                'ws_az=use1-az2,ws_proxy_target=proxy-produce,my-pod-1'
            )
        })

        it('keeps extra when only extra is configured (no prefix)', () => {
            process.env.KAFKA_CDP_PRODUCER_CLIENT_ID_EXTRA = 'warpstream_proxy_target=proxy-consume'
            expect(assembleKafkaClientId('CDP_PRODUCER', { rack: 'use1-az2', podName })).toEqual(
                'warpstream_proxy_target=proxy-consume,my-pod-1'
            )
        })

        it('reads env vars per-target, not globally', () => {
            process.env.KAFKA_MSK_PRODUCER_CLIENT_ID_PREFIX = 'msk'
            process.env.KAFKA_CONSUMER_CLIENT_ID_PREFIX = 'ws'
            expect(assembleKafkaClientId('MSK_PRODUCER', { rack: 'use1-az2', podName })).toEqual(
                'msk_az=use1-az2,my-pod-1'
            )
            expect(assembleKafkaClientId('CONSUMER', { rack: 'use1-az2', podName })).toEqual('ws_az=use1-az2,my-pod-1')
        })
    })

    describe('isAutoDeriveClientIdEnabled', () => {
        it('returns true only when env var is exactly "true"', () => {
            delete process.env.KAFKA_AUTO_DERIVE_CLIENT_ID
            expect(isAutoDeriveClientIdEnabled()).toBe(false)

            process.env.KAFKA_AUTO_DERIVE_CLIENT_ID = 'true'
            expect(isAutoDeriveClientIdEnabled()).toBe(true)

            process.env.KAFKA_AUTO_DERIVE_CLIENT_ID = 'false'
            expect(isAutoDeriveClientIdEnabled()).toBe(false)

            process.env.KAFKA_AUTO_DERIVE_CLIENT_ID = '1'
            expect(isAutoDeriveClientIdEnabled()).toBe(false)
        })
    })
})
