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

// test data_testid
test('data_testid', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://community.netdata.cloud/",
            "$elements": [
                {
                    "attr__data-testid": "date-picker::click-quick-selector::::21600",
                },
                {
                    "attr__href": "#menu_web_log_nginx"
                },
                {
                    "event": null,
                    "text": null,
                    "tag_name": "div",
                    "attr_class": [
                        "bjKBDB",
                        "styled__ShortPick-sc-1yj3701-6"
                    ],
                    "href": null,
                    "attr_id": null,
                    "nth_child": 1,
                    "nth_of_type": 1,
                    "attributes": {
                        "attr__class": "styled__ShortPick-sc-1yj3701-6 bjKBDB"
                    },
                    "order": 1
                },
                {
                    "event": null,
                    "text": "unshared",
                    "tag_name": "span",
                    "attr_class": [
                        "chart-legend-bottomstyled__DimensionLabel-ltgk2z-9",
                        "iMmOhf"
                    ],
                    "href": null,
                    "attr_id": null,
                    "nth_child": 2,
                    "nth_of_type": 1,
                    "attributes": {
                        "attr__class": "chart-legend-bottomstyled__DimensionLabel-ltgk2z-9 iMmOhf"
                    },
                    "order": 0
                },
                {
                    "$el_text": "unshared"
                },
                {
                    "event": null,
                    "text": "unshared",
                    "tag_name": "span",
                    "attr_class": [
                        "chart-legend-bottomstyled__DimensionLabel-ltgk2z-9",
                        "iMmOhf"
                    ],
                    "href": null,
                    "attr_id": null,
                    "nth_child": 2,
                    "nth_of_type": 1,
                    "attributes": {
                        "attr__class": "chart-legend-bottomstyled__DimensionLabel-ltgk2z-9 iMmOhf"
                    },
                    "order": 0

                },
                {
                    "attr__data-testid": "newyork_netdata_rocks_mem_ksm",
                    "attr__data-legend-position": "bottom",
                    "attr__data-netdata": "mem.ksm",
                }
            ]
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("community")
    expect(eventCopy['properties']['el_data_testid']).toEqual("date-picker::click-quick-selector::::21600")
})

// test data_ga
test('data_ga', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://community.netdata.cloud/",
            "$elements": [
                {
                    "attr__data-ga": "date-picker::click-quick-selector::::21600"
                },
                {
                    "attr__data-ga": "#menu_web_log_nginx",
                },
                {
                    "$el_text": "unshared"
                },
                {
                    "attr__data-id": "newyork_netdata_rocks_mem_ksm",
                    "attr__data-legend-position": "bottom",
                    "attr__data-netdata": "mem.ksm",
                }
            ]
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("community")
    expect(eventCopy['properties']['el_data_ga']).toEqual("date-picker::click-quick-selector::::21600")
    expect(eventCopy['properties']['el_data_ga_0']).toEqual("date-picker")
    expect(eventCopy['properties']['el_data_ga_1']).toEqual("click-quick-selector")
    expect(eventCopy['properties']['el_data_ga_2']).toEqual("")
    expect(eventCopy['properties']['el_text']).toEqual("unshared")
})

test('processEvent does not crash with identify', async () => {
    // create a random event
    const event0 = createIdentify()

    // must clone the event since `processEvent` will mutate it otherwise
    const event1 = await processEvent(clone(event0), getMeta())
    expect(event1).toEqual(event0)
})

// test event_source_community
test('event_source_community', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://community.netdata.cloud/",
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("community")
})

// test el_name
test('el_name', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://community.netdata.cloud/",
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
            "$current_url": "https://community.netdata.cloud/",
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
