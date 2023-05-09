import { convertKafkaJSHeadersToRdKafkaHeaders } from '../../src/utils/db/kafka-producer-wrapper'

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
