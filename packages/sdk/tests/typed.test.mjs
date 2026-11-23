import assert from 'node:assert/strict'
import { test } from 'node:test'

import { typed } from '@posthog/sdk/define'

class Client {
    sent = []
    distinctId = 'anonymous'
    #flags = { 'new-checkout': 'test' }
    capture(event, properties, options) {
        this.sent.push([event, properties, options])
        return { event }
    }
    getFeatureFlag(key) {
        return this.#flags[key]
    }
    identify(distinctId) {
        this.distinctId = distinctId
    }
}

test('the typed client sends through the client and keeps its other members working', () => {
    const client = new Client()
    const analytics = typed()(client)
    assert.deepEqual(analytics.capture('checkout_completed', { total_usd: 1 }, { send_instantly: true }), {
        event: 'checkout_completed',
    })
    analytics.captureRaw('anything', { a: 1 })
    analytics.identify('person')
    assert.deepEqual(client.sent, [
        ['checkout_completed', { total_usd: 1 }, { send_instantly: true }],
        ['anything', { a: 1 }, undefined],
    ])
    assert.equal(client.distinctId, 'person')
    assert.equal(analytics.distinctId, 'person')
    assert.equal(analytics.variant('new-checkout'), 'test')
    assert.equal(analytics.variant('missing'), undefined)
    assert.equal(typed(client).variant('new-checkout'), 'test')
})
