import { createPageview, resetMeta } from '@posthog/plugin-scaffold/test/utils'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

const defaultMeta = {
    config: {
        dedupMode: 'Event and Timestamp',
    },
}

describe('`Event and Timestamp` mode', () => {
    test('event UUID is properly generated', () => {
        const meta = resetMeta() as LegacyTransformationPluginMeta
        const event = processEvent({ ...createPageview(), timestamp: '2020-02-02T23:59:59.999999Z' }, meta)
        expect(event?.uuid).toEqual('1b2b7e1a-c059-5116-a6d2-eb1c1dd793bc')
    })
    test('same key properties produces the same UUID', () => {
        const meta = resetMeta() as LegacyTransformationPluginMeta
        const event1 = processEvent(
            { ...createPageview(), event: 'myPageview', timestamp: '2020-05-02T20:59:59.999999Z', ignoreMe: 'yes' },
            meta
        )
        const event2 = processEvent(
            {
                ...createPageview(),
                event: 'myPageview',
                timestamp: '2020-05-02T20:59:59.999999Z',
                differentProperty: 'indeed',
            },
            meta
        )
        expect(event1?.uuid).toBeTruthy()
        expect(event1?.uuid).toEqual(event2?.uuid)
    })
    test('different key properties produces a different UUID', () => {
        const meta = resetMeta() as LegacyTransformationPluginMeta
        const event1 = processEvent({ ...createPageview(), timestamp: '2020-05-02T20:59:59.999999Z' }, meta)
        const event2 = processEvent(
            {
                ...createPageview(),
                timestamp: '2020-05-02T20:59:59.999888Z', // note milliseconds are different
            },
            meta
        )
        expect(event1?.uuid).toBeTruthy()
        expect(event1?.uuid).not.toEqual(event2?.uuid)
    })
})

describe('`All Properties` mode', () => {
    test('event UUID is properly generated (all props)', () => {
        const meta = resetMeta({
            config: { ...defaultMeta.config, dedupMode: 'All Properties' },
        }) as LegacyTransformationPluginMeta
        const event = processEvent({ ...createPageview(), timestamp: '2020-02-02T23:59:59.999999Z' }, meta)
        expect(event?.uuid).toEqual('5a4e6d35-a9e4-50e2-9d97-4f7cc04e8b30')
    })
    test('same key properties produces the same UUID (all props)', () => {
        const meta = resetMeta({
            config: { ...defaultMeta.config, dedupMode: 'All Properties' },
        }) as LegacyTransformationPluginMeta
        const event1 = processEvent(
            {
                ...createPageview(),
                event: 'myPageview',
                timestamp: '2020-05-02T20:59:59.999999Z',
                properties: {
                    ...createPageview().properties,
                    customProp1: true,
                    customProp2: 'lgtm!',
                },
            },
            meta
        )
        const event2 = processEvent(
            {
                ...createPageview(),
                event: 'myPageview',
                timestamp: '2020-05-02T20:59:59.999999Z',
                properties: {
                    ...createPageview().properties,
                    customProp1: true,
                    customProp2: 'lgtm!',
                },
            },
            meta
        )
        expect(event1?.uuid).toBeTruthy()
        expect(event1?.uuid).toEqual(event2?.uuid)
    })
    test('different properties produce a different UUID (all props)', () => {
        const meta = resetMeta({
            config: { ...defaultMeta.config, dedupMode: 'All Properties' },
        }) as LegacyTransformationPluginMeta
        const event1 = processEvent(
            { ...createPageview(), timestamp: '2020-05-02T20:59:59.999999Z', properties: { customProp: '2' } },
            meta
        )
        const event2 = processEvent(
            {
                ...createPageview(),
                timestamp: '2020-05-02T20:59:59.999999Z',
                properties: { customProp: '1' },
            },
            meta
        )
        expect(event1?.uuid).toBeTruthy()
        expect(event1?.uuid).not.toEqual(event2?.uuid)
    })
})
