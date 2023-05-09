import { Message } from 'node-rdkafka-acosom'

import {
    convertKafkaJSHeadersToRdKafkaHeaders,
    convertRdKafkaHeadersToKafkaJSHeaders,
} from '../../src/utils/db/kafka-producer-wrapper'

test('can convert from KafkaJS headers to rdkafka headers', () => {
    expect(convertKafkaJSHeadersToRdKafkaHeaders()).toEqual(undefined)
    expect(convertKafkaJSHeadersToRdKafkaHeaders({})).toEqual([])
    expect(convertKafkaJSHeadersToRdKafkaHeaders({ foo: 'bar' })).toEqual([{ foo: Buffer.from('bar') }])
    expect(convertKafkaJSHeadersToRdKafkaHeaders({ foo: ['bar', 'baz'] })).toEqual([
        { foo: Buffer.from('bar') },
        { foo: Buffer.from('baz') },
    ])
    expect(convertKafkaJSHeadersToRdKafkaHeaders({ foo: ['bar', 'baz'], qux: 'quux' })).toEqual([
        { foo: Buffer.from('bar') },
        { foo: Buffer.from('baz') },
        { qux: Buffer.from('quux') },
    ])
    expect(convertKafkaJSHeadersToRdKafkaHeaders({ foo: undefined })).toEqual([])

    // We should be able to use strings and Buffers interchangeably
    expect(convertKafkaJSHeadersToRdKafkaHeaders({ foo: Buffer.from('bar') })).toEqual([{ foo: Buffer.from('bar') }])
    expect(convertKafkaJSHeadersToRdKafkaHeaders({ foo: 'bar' })).toEqual([{ foo: Buffer.from('bar') }])

    // We should be able to use strings and Buffers interchangeably in arrays
    expect(convertKafkaJSHeadersToRdKafkaHeaders({ foo: [Buffer.from('bar'), 'baz'] })).toEqual([
        { foo: Buffer.from('bar') },
        { foo: Buffer.from('baz') },
    ])
})

test('can convert from rdkafka headers to KafkaJS headers', () => {
    expect(convertRdKafkaHeadersToKafkaJSHeaders()).toEqual(undefined)
    expect(convertRdKafkaHeadersToKafkaJSHeaders([])).toEqual({})
    expect(convertRdKafkaHeadersToKafkaJSHeaders([{ foo: Buffer.from('bar') }])).toEqual({ foo: Buffer.from('bar') })
    expect(convertRdKafkaHeadersToKafkaJSHeaders([{ foo: Buffer.from('bar') }, { foo: Buffer.from('baz') }])).toEqual({
        foo: [Buffer.from('bar'), Buffer.from('baz')],
    })
    expect(
        convertRdKafkaHeadersToKafkaJSHeaders([
            { foo: Buffer.from('bar') },
            { foo: Buffer.from('baz') },
            { qux: Buffer.from('quux') },
        ])
    ).toEqual({ foo: [Buffer.from('bar'), Buffer.from('baz')], qux: Buffer.from('quux') })
})

test('can convert from rdkafka headers, to KafkaJS headers and back again', () => {
    let rdkafkaHeaders = [
        { foo: Buffer.from('bar') },
        { foo: Buffer.from('baz') },
        { qux: Buffer.from('quux') },
    ] as Message['headers']

    expect(convertKafkaJSHeadersToRdKafkaHeaders(convertRdKafkaHeadersToKafkaJSHeaders(rdkafkaHeaders))).toEqual(
        rdkafkaHeaders
    )

    rdkafkaHeaders = [{ foo: Buffer.from('bar') }] as Message['headers']

    expect(convertKafkaJSHeadersToRdKafkaHeaders(convertRdKafkaHeadersToKafkaJSHeaders(rdkafkaHeaders))).toEqual(
        rdkafkaHeaders
    )

    rdkafkaHeaders = [] as Message['headers']

    expect(convertKafkaJSHeadersToRdKafkaHeaders(convertRdKafkaHeadersToKafkaJSHeaders(rdkafkaHeaders))).toEqual(
        rdkafkaHeaders
    )

    rdkafkaHeaders = undefined

    expect(convertKafkaJSHeadersToRdKafkaHeaders(convertRdKafkaHeadersToKafkaJSHeaders(rdkafkaHeaders))).toEqual(
        undefined
    )
})
