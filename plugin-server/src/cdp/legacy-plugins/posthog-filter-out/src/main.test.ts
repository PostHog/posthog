import { expect, test, describe } from "@jest/globals";
import { createEvent } from "@posthog/plugin-scaffold/dist/test/utils";
import { PluginEvent } from "@posthog/plugin-scaffold";

import { Filter, PluginMeta, processEvent, setupPlugin } from "./main";

const filters: Filter[] = [
    {
        property: "$host",
        type: "string",
        operator: "not_contains",
        value: "localhost",
    },
    {
        property: "foo",
        type: "number",
        operator: "gt",
        value: 10,
    },
    {
        property: "bar",
        type: "boolean",
        operator: "is",
        value: true,
    },
];

const meta = {
    global: { filters, eventsToDrop: ["to_drop_event"] },
} as PluginMeta;

test("Event satisfies all conditions and passes", () => {
    const event = createEvent({
        event: "test event",
        properties: {
            $host: "example.com",
            foo: 20,
            bar: true,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, meta);
    expect(processedEvent).toEqual(event);
});

test("Event does not satisfy one condition and is dropped", () => {
    const event = createEvent({
        event: "test event",
        properties: {
            $host: "localhost:8000",
            foo: 20,
            bar: true,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, meta);
    expect(processedEvent).toBeUndefined();
});

test("Event does not satisfy any condition and is dropped", () => {
    const event = createEvent({
        event: "test event",
        properties: {
            $host: "localhost:8000",
            foo: 5,
            bar: false,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, meta);
    expect(processedEvent).toBeUndefined();
});

test("Event is marked to be dropped is dropped", () => {
    const event = createEvent({
        event: "to_drop_event",
        properties: {
            $host: "example.com",
            foo: 20,
            bar: true,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, meta);
    expect(processedEvent).toBeUndefined();
});

test("Event is marked to be dropped when a property is undefined", () => {
    const event = createEvent({
        event: "test_event",
        properties: {
            $host: undefined,
            foo: 20,
            bar: true,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, meta);
    expect(processedEvent).toBeUndefined();
});

test("Event is marked to be dropped when a property is undefined but keepUndefinedProperties", () => {
    const event = createEvent({
        event: "test_event",
        properties: {
            $host: undefined,
            foo: 20,
            bar: true,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, {
        global: { ...meta.global, keepUndefinedProperties: true },
    } as PluginMeta);
    expect(processedEvent).toEqual(event);
});

function setup(config) {
    const global: any = {};

    setupPlugin({
        config,
        global,
        attachments: { filters: { contents: JSON.stringify(filters) } },
    } as any);

    return global;
}

test("setupPlugin() parsing eventsToDrop", () => {
    expect(setup({ eventsToDrop: "foo, bar  " }).eventsToDrop).toEqual([
        "foo",
        "bar",
    ]);
    expect(setup({ eventsToDrop: "$foo,$bar" }).eventsToDrop).toEqual([
        "$foo",
        "$bar",
    ]);
    expect(setup({}).eventsToDrop).toEqual([]);
});

test("setupPlugin() parsing keepUndefinedProperties", () => {
    expect(
        setup({ keepUndefinedProperties: "Yes" }).keepUndefinedProperties
    ).toEqual(true);
    expect(
        setup({ keepUndefinedProperties: "No" }).keepUndefinedProperties
    ).toEqual(false);
    expect(setup({}).keepUndefinedProperties).toEqual(false);
});

describe("empty filters", () => {
    const meta_no_filters = {
        global: { filters: [], eventsToDrop: ["to_drop_event"] },
    } as PluginMeta;

    test("Event satisfies all conditions and passes", () => {
        const event = createEvent({
            event: "test event",
            properties: {
                $host: "example.com",
                foo: 20,
                bar: true,
            },
        }) as unknown as PluginEvent;
        const processedEvent = processEvent(event, meta_no_filters);
        expect(processedEvent).toEqual(event);
    });

    test("Event is marked to be dropped is dropped", () => {
        const event = createEvent({
            event: "to_drop_event",
            properties: {
                $host: "example.com",
                foo: 20,
                bar: true,
            },
        }) as unknown as PluginEvent;
        const processedEvent = processEvent(event, meta_no_filters);
        expect(processedEvent).toBeUndefined();
    });

    test("setupPlugin() without any config works", () => {
        const global: any = {};
        setupPlugin({ config: {}, global, attachments: { filters: null } } as any);
        expect(global.filters).toEqual([]);
        expect(global.eventsToDrop).toEqual([]);
        expect(global.keepUndefinedProperties).toEqual(false);
    });

    test("setupPlugin() with other config works", () => {
        const global: any = {};
        setupPlugin({
            config: { eventsToDrop: "foo,bar", keepUndefinedProperties: "Yes" },
            global,
            attachments: { filters: null },
        } as any);
        expect(global.filters).toEqual([]);
        expect(global.eventsToDrop).toEqual(["foo", "bar"]);
        expect(global.keepUndefinedProperties).toEqual(true);
    });
});


const filters_or: Filter[][] = [
    [
        {
            property: "$host",
            type: "string",
            operator: "not_contains",
            value: "localhost",
        },
        {
            property: "foo",
            type: "number",
            operator: "gt",
            value: 10,
        },
    ],
    [
        {
            property: "bar",
            type: "boolean",
            operator: "is",
            value: true,
        },
    ],
];

const meta_or = {
    global: { filters: filters_or, eventsToDrop: ["to_drop_event"] },
} as PluginMeta;

test("Event satisfies at least one filter group and passes", () => {
    const event = createEvent({
        event: "test event",
        properties: {
            $host: "example.com",
            foo: 5,
            bar: true,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, meta_or);
    expect(processedEvent).toEqual(event);
});

test("Event satisfies no filter groups and is dropped", () => {
    const event = createEvent({
        event: "test event",
        properties: {
            $host: "localhost:8000",
            foo: 5,
            bar: false,
        },
    }) as unknown as PluginEvent;
    const processedEvent = processEvent(event, meta_or);
    expect(processedEvent).toBeUndefined();
});
