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
            netdata_version: 'v1.29.2',
        },
    })
})

test('setupPlugin', async () => {
    expect(getMeta().config.netdata_version).toEqual('v1.29.2')
    await setupPlugin(getMeta())
    expect(getMeta().global.setupDone).toEqual(true)
})

// test event_source_staging
test('event_source_staging', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://staging.netdata.cloud/",
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("staging")
})

// test el_name
test('el_name', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://staging.netdata.cloud/",
            "$elements": [
                {
                    "attr__foo": "foo"
                },
                {
                    "attr__bar": "bar",
                },
                {
                    "attr__data-id": "newyork_netdata_rocks_mem_ksm",
                    "attr__data-legend-position": "bottom",
                    "attr__data-netdata": "mem.ksm",
                    "attr__name": "foo",
                }
            ]
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['el_name']).toEqual("foo")
})

// test el_class
test('el_class', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://staging.netdata.cloud/",
            "$elements": [
                {
                    "attr__foo": "foo"
                },
                {
                    "attr__bar": "bar",
                    "attributes": {
                        "attr__aria-label": "my_aria_label",
                        "attr__class": "my_att_class"
                    },
                },
                {
                    "attr__class": "my_class"
                }
            ]
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['el_class']).toEqual("my_class")
})
