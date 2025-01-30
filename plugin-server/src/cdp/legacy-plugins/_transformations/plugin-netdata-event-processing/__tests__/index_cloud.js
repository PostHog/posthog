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
            "$current_url": "https://app.netdata.cloud/",
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
    expect(eventCopy['properties']['event_source']).toEqual("cloud")
    expect(eventCopy['properties']['el_data_testid']).toEqual("date-picker::click-quick-selector::::21600")
})

// test data_ga
test('data_ga', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/",
            "$elements": [
                {
                    "attr__data-ga": "some-category::some-action::some-label::some-value",
                },
                {
                    "attr__data-ga": "#menu_web_log_nginx",
                },
                {
                    "$el_text": "unshared"
                },
                {
                    "attr__data-ga": "date-picker::click-quick-selector::::21600",
                    "attr__data-id": "newyork_netdata_rocks_mem_ksm",
                    "attr__data-legend-position": "bottom",
                    "attr__data-netdata": "mem.ksm",
                }
            ]
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("cloud")
    expect(eventCopy['properties']['el_data_ga']).toEqual("some-category::some-action::some-label::some-value")
    expect(eventCopy['properties']['el_data_ga_inner']).toEqual("some-category::some-action::some-label::some-value")
    expect(eventCopy['properties']['el_data_ga_outer']).toEqual("date-picker::click-quick-selector::::21600")
    expect(eventCopy['properties']['el_data_ga_0']).toEqual("some-category")
    expect(eventCopy['properties']['el_data_ga_1']).toEqual("some-action")
    expect(eventCopy['properties']['el_data_ga_2']).toEqual("some-label")
    expect(eventCopy['properties']['event_category']).toEqual("some-category")
    expect(eventCopy['properties']['event_action']).toEqual("some-action")
    expect(eventCopy['properties']['event_label']).toEqual("some-label")
    expect(eventCopy['properties']['event_value']).toEqual("some-value")
    expect(eventCopy['properties']['el_text']).toEqual("unshared")
})

test('processEvent does not crash with identify', async () => {
    // create a random event
    const event0 = createIdentify()

    // must clone the event since `processEvent` will mutate it otherwise
    const event1 = await processEvent(clone(event0), getMeta())
    expect(event1).toEqual(event0)
})

// test event_source_cloud
test('event_source_cloud', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/",
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("cloud")
})

// test event_source_cloud_identify
test('event_source_cloud_identify', async () => {
    const eventExample = {
        "event": "$identify",
        "distinct_id": "dev-test",
        "properties": {
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("cloud")
    expect(eventCopy['properties']['event_ph']).toEqual("$identify")
})

// test data_track
test('data_track', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/",
            "$elements": [
                {
                    "attr__data-track": "foobar"
                },
                {
                    "attr__data-track": "date-picker::click-quick-selector::::21600"
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
    expect(eventCopy['properties']['event_source']).toEqual("cloud")
    expect(eventCopy['properties']['el_data_track_outer']).toEqual("date-picker::click-quick-selector::::21600")
    expect(eventCopy['properties']['el_data_track_outer_0']).toEqual("date-picker")
    expect(eventCopy['properties']['el_data_track_outer_1']).toEqual("click-quick-selector")
    expect(eventCopy['properties']['el_data_track_outer_2']).toEqual("")
    expect(eventCopy['properties']['el_text']).toEqual("unshared")
    expect(eventCopy['properties']['el_data_track_outer']).toEqual("date-picker::click-quick-selector::::21600")
    expect(eventCopy['properties']['el_data_track_inner']).toEqual("foobar")
})

// test el_name
test('el_name', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/",
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

// test pathname
test('pathname', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/a/b/c/d",
            "$pathname": "/a/b/c/d"
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['pathname_1']).toEqual("a")
    expect(eventCopy['properties']['pathname_2']).toEqual("b")
    expect(eventCopy['properties']['pathname_3']).toEqual("c")
    expect(eventCopy['properties']['pathname_4']).toEqual("d")
    expect(eventCopy['properties']['event_source']).toEqual("cloud")
})

// test pathname
test('pathname_real', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/account/sso-agent?id=e6bfbf32-e89f-11ec-a180-233f485cb8df",
            "$pathname": "/account/sso-agent?id=e6bfbf32-e89f-11ec-a180-233f485cb8df"
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['pathname_1']).toEqual("account")
    expect(eventCopy['properties']['pathname_2']).toEqual("sso-agent?id=e6bfbf32-e89f-11ec-a180-233f485cb8df")
    expect(eventCopy['properties']['event_source']).toEqual("cloud")

})

// test el_class
test('el_class', async () => {
    const eventExample = {
        "event": "$autocapture",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/",
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

// test cloud_agent_19999
test('cloud_agent_19999', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://10.10.10.10:19999/spaces/foo",
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("cloud_agent")
})

// test cloud_agent_spaces
test('cloud_agent_spaces', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://some.netdata/spaces/foo",
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("cloud_agent")
})

// test cloud_spaces
test('cloud_agent_spaces', async () => {
    const eventExample = {
        "event": "$pageview",
        "distinct_id": "dev-test",
        "properties": {
            "$current_url": "https://app.netdata.cloud/spaces/foobar",
        }
    }
    const event = createEvent(eventExample)
    const eventCopy = await processEvent(clone(event), getMeta())
    expect(eventCopy['properties']['event_source']).toEqual("cloud")
})
