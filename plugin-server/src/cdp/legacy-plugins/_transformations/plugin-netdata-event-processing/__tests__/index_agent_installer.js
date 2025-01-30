const {
    createEvent,
    createIdentify,
    createPageview,
    createCache,
    getMeta,
    resetMeta,
    clone,
} = require('posthog-plugins/test/utils.js')
const { setupPlugin, processEvent } = require('../index')

const netdataPluginVersion = '0.0.15'

beforeEach(() => {
    resetMeta({
        config: {
            netdata_version: 'v1.41.0',
        },
    })
})

test('setupPlugin', async () => {
    expect(getMeta().config.netdata_version).toEqual('v1.41.0')
    await setupPlugin(getMeta())
    expect(getMeta().global.setupDone).toEqual(true)
})

// test event_source
test('event_source', async () => {
    const event = createEvent({ event: 'test event', properties: { "$current_url":"agent installer"} })
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("agent installer")
})

// test install_options_easy
test('install_options_easy', async () => {
    const event = createEvent({
        event: 'test event', properties: {
            "$current_url":"agent installer",
            "install_options": "--dont-start-it --dont-wait --claim-token 3gciBd6HYGp7Z2v2fJDd6meraFoUT4QpVYcHTE253KujJPStNQhXi9cicTgEEc_mNiQNxAYtHlZNpC1a2NQz57fV6aZaa2vPvyPYw9hsv_SOfzfWxMdQ6L-PPOyM9e9N2HAVp7E --claim-rooms 22ff1e07-8e9c-41ad-b141-5bd95fbf95d1 --claim-url https://app.netdata.cloud --foo"
        }
    })
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("agent installer")
    expect(eventCopy['properties']['opt_dont_start_it']).toEqual('')
    expect(eventCopy['properties']['opt_dont_wait']).toEqual('')
    expect(eventCopy['properties']['opt_claim_token']).toEqual('3gciBd6HYGp7Z2v2fJDd6meraFoUT4QpVYcHTE253KujJPStNQhXi9cicTgEEc_mNiQNxAYtHlZNpC1a2NQz57fV6aZaa2vPvyPYw9hsv_SOfzfWxMdQ6L-PPOyM9e9N2HAVp7E')
    expect(eventCopy['properties']['opt_claim_url']).toEqual('https://app.netdata.cloud')
    expect(eventCopy['properties']['opt_foo']).toEqual('')
})



