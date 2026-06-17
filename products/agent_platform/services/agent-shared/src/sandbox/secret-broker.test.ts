import { SecretBroker } from './secret-broker'

describe('SecretBroker', () => {
    it('mints unique nonces per secret and round-trips via substitute', () => {
        const broker = new SecretBroker()
        const map = broker.mintSessionMap('sess1', { ACME: 'topsecret', OTHER: 'abc' })
        expect(map.ACME).toMatch(/^nonce_[a-f0-9]+/)
        expect(map.OTHER).toMatch(/^nonce_[a-f0-9]+/)
        expect(map.ACME).not.toBe(map.OTHER)
        const out = broker.substitute('sess1', `Authorization: Bearer ${map.ACME}, X-Other: ${map.OTHER}`)
        expect(out).toBe('Authorization: Bearer topsecret, X-Other: abc')
    })

    it('scrub redacts raw secret values from output', () => {
        const broker = new SecretBroker()
        broker.mintSessionMap('sess1', { K: 'topsecret' })
        expect(broker.scrub('sess1', 'leaked topsecret in logs')).toBe('leaked [REDACTED] in logs')
    })

    it('release clears the session', () => {
        const broker = new SecretBroker()
        const map = broker.mintSessionMap('sess1', { K: 'v' })
        broker.release('sess1')
        expect(broker.substitute('sess1', map.K)).toBe(map.K) // no substitution after release
    })

    it('isolates per session', () => {
        const broker = new SecretBroker()
        const a = broker.mintSessionMap('a', { K: 'alpha' })
        const b = broker.mintSessionMap('b', { K: 'beta' })
        expect(broker.substitute('a', a.K)).toBe('alpha')
        expect(broker.substitute('b', b.K)).toBe('beta')
        expect(broker.substitute('a', b.K)).toBe(b.K) // b's nonce isn't in a's map
    })
})
