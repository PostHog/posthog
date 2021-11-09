import { randomBytes } from 'crypto'

import { LogLevel } from '../src/types'
import {
    bufferToStream,
    cloneObject,
    escapeClickHouseString,
    getFileFromArchive,
    getFileFromTGZ,
    getFileFromZip,
    groupBy,
    sanitizeSqlIdentifier,
    setLogLevel,
    stringify,
    UUID,
    UUIDT,
} from '../src/utils/utils'
import { parseDate } from '../src/worker/ingestion/utils'

// .zip in Base64: github repo posthog/helloworldplugin
const zip =
    'UEsDBAoAAAAAAA8LbVEAAAAAAAAAAAAAAAAjAAkAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9VVAUAAc9Qrl9QSwMECgAAAAgADwttUQT7a+JUAAAAdQAAAC4ACQBoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uLy5wcmV0dGllcnJjVVQFAAHPUK5fq+ZSAAKlkqLEzJzMvHTn/NzcRCUrBaXUYlMlHahcYlJ4ZkpJBlDYBCpUnJqbCeSmJeYUp8KEgLpzUgNL80tSgTIlRaUwiYKizLwSmAGGRgZctVwAUEsDBAoAAAAIAA8LbVG/Zg9y6wAAAPMBAAArAAkAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9pbmRleC5qc1VUBQABz1CuX31RTUvEMBC951eMi5AUS1E8e9Sz4FFE0jjNBrKTkkxcZOl/N9u0hyo0hyHDe/PefOj0QwaGTIZdIEjIeXz12TpSFzCBBmdhauAioLySp+Cx88GqwxsyO7KQR+AjAqM+3Ryaf7yq0YhJCL31GmMwmNLzNxIrvMYWVs8WjDZFdWPNJWZijPAE+qwdV1JnkZVcINnC/dLEjKUttgrcwUMjZpoboJp3pZ8RIztMq+n1/cXe5RG9D/KjNCHPIfovucPtdZyZdaqupDvk27XPWjH/d+je9Z+UT/1SUNKXZbXqsa5gqiPGctRIVaHc4RdQSwMECgAAAAgADwttUVpiCFkvAAAAOQAAACkACQBoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL2xpYi5qc1VUBQABz1CuX0srzUsuyczPU8jJTHKDsTXySnOTUos0Faq5FICgKLWktChPASKooKVgZM1VywUAUEsDBAoAAAAIAA8LbVE7Twti+wAAAO0BAAAvAAkAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9wYWNrYWdlLmpzb25VVAUAAc9Qrl+VUbtOAzEQ7O8rjJHSQO6S9noEFEgUlGkud4vtyOe1dm1IFOXf8eNE0qazZ2ZnvONzI4R0wwyyF9IjB41qrcFa/EWy09rbqIyTz1n2A8QGXVZu2k27regEPJLxYWFeCSCIoEEUg4cqmgdTWOMmOLYHrmgd5ESc0zUBAThkGYwaxU6+ECH1wqHIhGAPo/k2MO2kWK0EHE0QW5kmL8WNIL3fBKTTjeHJl82UCSUyQZHsgjzpEDz3XZfOOu7bEefuM1Xwhqq7VlAbaLPDf9QQU0+Ubeoi1ozguCR9vH9VbB/VzWZL6h2JnWGOwNdQjTP4QcGdPo8Ew5T+t7k0f1BLAwQKAAAACAAPC21Ru8C8oc0AAABTAQAALgAJAGhlbGxvd29ybGRwbHVnaW4taW1hZ2VsZXNzLXZlcnNpb24vcGx1Z2luLmpzb25VVAUAAc9Qrl9tjz1rwzAQhnf/iquXLCHesxQytKVToEPms3WWr8g6VzqRL/LfKymQdOggxPu8zwvStQFoPc7UbqGdyDk5SnBmccmyb9elTcHVUnWJ266zrFPqN4PM3V6ifojt/t8ZikPgRVl82b8HIgWdCA7FBPQG3kQAYYdhDZ9fQIaL/HKfz8h1x97QafMd79RxX2C+HmgQP7LN9JpTzj2GR/jzucOEuorAvr4hS691Xh09L9WJGtjbJzc0YnJaqh4vTx7oJ3Egk4sRXaTKb005t+YXUEsBAgAACgAAAAAADwttUQAAAAAAAAAAAAAAACMACQAAAAAAAAAQAAAAAAAAAGhlbGxvd29ybGRwbHVnaW4taW1hZ2VsZXNzLXZlcnNpb24vVVQFAAHPUK5fUEsBAgAACgAAAAgADwttUQT7a+JUAAAAdQAAAC4ACQAAAAAAAQAAAAAASgAAAGhlbGxvd29ybGRwbHVnaW4taW1hZ2VsZXNzLXZlcnNpb24vLnByZXR0aWVycmNVVAUAAc9Qrl9QSwECAAAKAAAACAAPC21Rv2YPcusAAADzAQAAKwAJAAAAAAABAAAAAADzAAAAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9pbmRleC5qc1VUBQABz1CuX1BLAQIAAAoAAAAIAA8LbVFaYghZLwAAADkAAAApAAkAAAAAAAEAAAAAADACAABoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL2xpYi5qc1VUBQABz1CuX1BLAQIAAAoAAAAIAA8LbVE7Twti+wAAAO0BAAAvAAkAAAAAAAEAAAAAAK8CAABoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL3BhY2thZ2UuanNvblVUBQABz1CuX1BLAQIAAAoAAAAIAA8LbVG7wLyhzQAAAFMBAAAuAAkAAAAAAAEAAAAAAAAEAABoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL3BsdWdpbi5qc29uVVQFAAHPUK5fUEsFBgAAAAAGAAYATAIAACIFAAAoAGQ1YWExZDJiOGE1MzRmMzdjZDkzYmU0OGIyMTRmNDkwZWY5ZWU5MDQ='

// .tar.gz in Base64: NPM package posthog-helloworld-plugin v0.0.1
const tgz =
    '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'

test('getFileFromTGZ & getFileFromArchive', async () => {
    const buffer = Buffer.from(tgz, 'base64')

    const packageJson1 = await getFileFromTGZ(buffer, 'package.json')
    expect(packageJson1).toBeDefined()
    expect(JSON.parse(packageJson1!.toString())['version']).toEqual('0.0.0')

    const packageJson2 = await getFileFromArchive(buffer, 'package.json')
    expect(packageJson2).toBeDefined()
    expect(JSON.parse(packageJson2!.toString())['version']).toEqual('0.0.0')

    const missingJson1 = await getFileFromTGZ(buffer, 'missing.json')
    expect(missingJson1).toEqual(null)

    const missingJson2 = await getFileFromArchive(buffer, 'missing.json')
    expect(missingJson2).toEqual(null)

    await expect(getFileFromTGZ(Buffer.from('ha!@#!@2ha'), 'broken.json')).rejects.toThrow()
    await expect(getFileFromArchive(Buffer.from('haha'), 'broken.json')).rejects.toThrow()
})

test('getFileFromZip & getFileFromArchive', async () => {
    const buffer = Buffer.from(zip, 'base64')

    const packageJson1 = getFileFromZip(buffer, 'package.json')
    expect(packageJson1).toBeDefined()
    expect(JSON.parse(packageJson1!.toString())['version']).toEqual('0.0.1')

    const packageJson2 = await getFileFromArchive(buffer, 'package.json')
    expect(packageJson2).toBeDefined()
    expect(JSON.parse(packageJson2!.toString())['version']).toEqual('0.0.1')

    const missingJson1 = getFileFromZip(buffer, 'missing.json')
    expect(missingJson1).toEqual(null)

    const missingJson2 = await getFileFromArchive(buffer, 'missing.json')
    expect(missingJson2).toEqual(null)

    expect(() => getFileFromZip(Buffer.from('haha'), 'broken.json')).toThrow()
    await expect(getFileFromArchive(Buffer.from('haha'), 'broken.json')).rejects.toThrow()
})

test('bufferToStream', () => {
    const buffer = Buffer.from(zip, 'base64')
    const stream = bufferToStream(buffer)
    expect(stream.read()).toEqual(buffer)
})

test('setLogLevel', () => {
    function resetMocks() {
        console.debug = jest.fn()
        console.info = jest.fn()
        console.log = jest.fn()
        console.warn = jest.fn()
        console.error = jest.fn()
    }

    resetMocks()
    setLogLevel(LogLevel.Debug)
    console.debug('debug')
    console.info('debug')
    console.log('debug')
    console.warn('debug')
    console.error('debug')
    expect(console.debug).toHaveBeenCalledWith('debug')
    expect(console.info).toHaveBeenCalledWith('debug')
    expect(console.log).toHaveBeenCalledWith('debug')
    expect(console.warn).toHaveBeenCalledWith('debug')
    expect(console.error).toHaveBeenCalledWith('debug')

    resetMocks()
    setLogLevel(LogLevel.Info)
    console.debug('info')
    console.info('info')
    console.log('info')
    console.warn('info')
    console.error('info')
    expect((console.debug as any)._original).toBeDefined()
    expect(console.info).toHaveBeenCalledWith('info')
    expect(console.log).toHaveBeenCalledWith('info')
    expect(console.warn).toHaveBeenCalledWith('info')
    expect(console.error).toHaveBeenCalledWith('info')

    resetMocks()
    setLogLevel(LogLevel.Log)
    console.debug('log')
    console.info('log')
    console.log('log')
    console.warn('log')
    console.error('log')
    expect((console.debug as any)._original).toBeDefined()
    expect((console.info as any)._original).toBeDefined()
    expect(console.log).toHaveBeenCalledWith('log')
    expect(console.warn).toHaveBeenCalledWith('log')
    expect(console.error).toHaveBeenCalledWith('log')

    resetMocks()
    setLogLevel(LogLevel.Warn)
    console.debug('warn')
    console.info('warn')
    console.log('warn')
    console.warn('warn')
    console.error('warn')
    expect((console.debug as any)._original).toBeDefined()
    expect((console.info as any)._original).toBeDefined()
    expect((console.log as any)._original).toBeDefined()
    expect(console.warn).toHaveBeenCalledWith('warn')
    expect(console.error).toHaveBeenCalledWith('warn')

    resetMocks()
    setLogLevel(LogLevel.Error)
    console.debug('error')
    console.info('error')
    console.log('error')
    console.warn('error')
    console.error('error')
    expect((console.debug as any)._original).toBeDefined()
    expect((console.info as any)._original).toBeDefined()
    expect((console.log as any)._original).toBeDefined()
    expect((console.warn as any)._original).toBeDefined()
    expect(console.error).toHaveBeenCalledWith('error')

    resetMocks()
    setLogLevel(LogLevel.None)
    console.debug('none')
    console.info('none')
    console.log('none')
    console.warn('none')
    console.error('none')
    expect((console.debug as any)._original).toBeDefined()
    expect((console.info as any)._original).toBeDefined()
    expect((console.log as any)._original).toBeDefined()
    expect((console.warn as any)._original).toBeDefined()
    expect((console.error as any)._original).toBeDefined()
})

test('cloneObject', () => {
    const o1 = ['string', 'value']
    expect(cloneObject(o1)).toEqual(o1)
    expect(cloneObject(o1) === o1).toBe(false)

    const o2 = { key: 'value' }
    expect(cloneObject(o2)).toEqual(o2)
    expect(cloneObject(o2) === o2).toBe(false)

    const o3 = { key: 'value', nested: ['a1', 'a2'], nestedObj: { key: 'other' } }
    expect(cloneObject(o3)).toEqual(o3)
    expect(cloneObject(o3) === o3).toBe(false)
    expect((cloneObject(o3) as typeof o3).nested === o3.nested).toBe(false)
    expect((cloneObject(o3) as typeof o3).nestedObj === o3.nestedObj).toBe(false)

    const o4 = null
    expect(cloneObject(o4)).toEqual(o4)
    expect(cloneObject(o4) === o4).toBe(true)

    const o5 = 'string'
    expect(cloneObject(o5)).toEqual(o5)
    expect(cloneObject(o5) === o5).toBe(true)
})

describe('UUID', () => {
    describe('#constructor', () => {
        it('works with a valid string', () => {
            const uuid = new UUID('99aBcDeF-1234-4321-0000-dcba87654321')
            expect(uuid.array).toStrictEqual(
                new Uint8Array([
                    0x99, 0xab, 0xcd, 0xef, 0x12, 0x34, 0x43, 0x21, 0, 0, 0xdc, 0xba, 0x87, 0x65, 0x43, 0x21,
                ])
            )
        })

        it('throws on an invalid string', () => {
            expect(() => new UUID('99aBcDeF-1234-4321-WXyz-dcba87654321')).toThrow() // "WXyz" are not hexadecimal
            expect(() => new UUID('99aBcDeF123443210000dcba87654321')).toThrow() // lack of hyphens
            expect(() => new UUID('99aBcDeF-1234-4321-0000-dcba87654321A')).toThrow() // one character too many
            expect(() => new UUID('99aBcDeF-1234-4321-0000-dcba8765432')).toThrow() // one character too few
            expect(() => new UUID('')).toThrow() // empty string
        })

        it('works with a Uint8Array', () => {
            for (let i = 0; i < 10; i++) {
                const uuid = new UUID(
                    new Uint8Array([
                        0x99, 0xab, 0xcd, 0xef, 0x12, 0x34, 0x43, 0x21, 0, 0, 0xdc, 0xba, 0x87, 0x65, 0x43, 0x21,
                    ])
                )
                expect(uuid.array).toStrictEqual(
                    new Uint8Array([
                        0x99, 0xab, 0xcd, 0xef, 0x12, 0x34, 0x43, 0x21, 0, 0, 0xdc, 0xba, 0x87, 0x65, 0x43, 0x21,
                    ])
                )
            }
        })

        it('works with a random buffer', () => {
            for (let i = 0; i < 10; i++) {
                const uuid = new UUID(randomBytes(16))
                expect(uuid.array).toHaveLength(16)
            }
        })
    })

    describe('#valueOf', () => {
        it('returns the right big integer', () => {
            const uuid = new UUID('99aBcDeF-1234-4321-0000-dcba87654321')
            // eslint-disable-next-line @typescript-eslint/ban-ts-comment
            // @ts-ignore
            expect(uuid.valueOf()).toStrictEqual(0x99abcdef123443210000dcba87654321n)
        })
    })

    describe('#toString', () => {
        it('returns the right string', () => {
            const original = '99aBcDeF-1234-4321-0000-dcba87654321'
            const uuid = new UUID(original)
            const uuidString = uuid.toString()
            // 32 hexadecimal digits + 4 hyphens
            expect(uuidString).toHaveLength(36)
            expect(uuidString).toStrictEqual(original.toLowerCase())
        })
    })
})

describe('UUIDT', () => {
    it('is well-formed', () => {
        const uuidt = new UUIDT()
        const uuidtString = uuidt.toString()
        // UTC timestamp matching (roughly, only comparing the beginning as the timestamp's end inevitably drifts away)
        expect(uuidtString.slice(0, 8)).toEqual(Date.now().toString(16).padStart(12, '0').slice(0, 8))
        // series matching
        expect(uuidtString.slice(14, 18)).toEqual('0000')
    })
})

describe('sanitizeSqlIdentifier', () => {
    it('removes all characters that are neither letter, digit or underscore and adds quotes around identifier', () => {
        const rawIdentifier = 'some_field"; DROP TABLE actually_an_injection-9;'

        const sanitizedIdentifier = sanitizeSqlIdentifier(rawIdentifier)

        expect(sanitizedIdentifier).toStrictEqual('some_fieldDROPTABLEactually_an_injection9')
    })
})

describe('escapeClickHouseString', () => {
    it('escapes single quotes and slashes', () => {
        const rawString = "insert'escape \\"

        const sanitizedString = escapeClickHouseString(rawString)

        expect(sanitizedString).toStrictEqual("insert\\'escape \\\\")
    })
})

describe('groupBy', () => {
    it('groups simple objects', () => {
        const objects = [
            { i: 2, foo: 'x' },
            { i: 2, foo: 'y' },
            { i: 4, foo: 'x' },
            { i: 7, foo: 'z' },
        ]

        const groupingByI = groupBy(objects, 'i')
        expect(groupingByI).toEqual({
            2: [
                { i: 2, foo: 'x' },
                { i: 2, foo: 'y' },
            ],
            4: [{ i: 4, foo: 'x' }],
            7: [{ i: 7, foo: 'z' }],
        })

        const groupingByFoo = groupBy(objects, 'foo')
        expect(groupingByFoo).toEqual({
            x: [
                { i: 2, foo: 'x' },
                { i: 4, foo: 'x' },
            ],
            y: [{ i: 2, foo: 'y' }],
            z: [{ i: 7, foo: 'z' }],
        })
    })

    it('handles undefineds', () => {
        const objects = [{ i: 2, foo: 'x' }, { i: 2, foo: 'y' }, { i: 4, foo: 'x' }, { foo: 'z' }]

        const groupingByI = groupBy(objects, 'i')
        expect(groupingByI).toEqual({
            2: [
                { i: 2, foo: 'x' },
                { i: 2, foo: 'y' },
            ],
            4: [{ i: 4, foo: 'x' }],
            undefined: [{ foo: 'z' }],
        })
    })

    it('works in flat mode', () => {
        const objects = [
            { i: 2, foo: 'x' },
            { i: 4, foo: 'x' },
            { i: 7, foo: 'z' },
        ]

        const groupingByI = groupBy(objects, 'i', true)
        expect(groupingByI).toEqual({
            2: { i: 2, foo: 'x' },
            4: { i: 4, foo: 'x' },
            7: { i: 7, foo: 'z' },
        })
    })

    it("doesn't work in flat mode if multiple values match a single key", () => {
        const objects = [
            { i: 2, foo: 'x' },
            { i: 2, foo: 'y' },
            { i: 4, foo: 'x' },
            { i: 7, foo: 'z' },
        ]

        expect(() => groupBy(objects, 'i', true)).toThrowError(
            'Key "i" has more than one matching value, which is not allowed in flat groupBy!'
        )
    })
})

describe('stringify', () => {
    it('leaves strings unaffected', () => {
        expect(stringify('test!')).toStrictEqual('test!')
    })

    it('transforms numbers into strings', () => {
        expect(stringify(3)).toStrictEqual('3')
        expect(stringify(21.37)).toStrictEqual('21.37')
    })

    it('transforms nullish values into strings', () => {
        expect(stringify(null)).toStrictEqual('null')
        expect(stringify(undefined)).toStrictEqual('undefined')
    })

    it('transforms object values into strings', () => {
        expect(stringify({})).toStrictEqual('{}')
        expect(stringify([])).toStrictEqual('[]')
    })
})

describe('parseDate', () => {
    const timestamps = [
        '2021-10-29',
        '2021-10-29 00:00:00',
        '2021-10-29 00:00:00.000000',
        '2021-10-29T00:00:00.000Z',
        '2021-10-29 00:00:00+00:00',
        '2021-10-29T00:00:00.000-00:00',
        '2021-10-29T00:00:00.000',
        '2021-10-29T00:00:00.000+00:00',
        '2021-W43-5',
        '2021-302',
    ]

    test.each(timestamps)('parses %s', (timestamp) => {
        const parsedTimestamp = parseDate(timestamp)
        expect(parsedTimestamp.year).toBe(2021)
        expect(parsedTimestamp.month).toBe(10)
        expect(parsedTimestamp.day).toBe(29)
        expect(parsedTimestamp.hour).toBe(0)
        expect(parsedTimestamp.minute).toBe(0)
        expect(parsedTimestamp.second).toBe(0)
        expect(parsedTimestamp.millisecond).toBe(0)
    })
})
