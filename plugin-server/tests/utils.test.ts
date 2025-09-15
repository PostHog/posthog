import { randomBytes } from 'crypto'
import { DateTime } from 'luxon'

import { eventPassesMetadataSwitchoverTest, parseSessionRecordingV2MetadataSwitchoverDate } from '~/main/utils'

import { ClickHouseTimestamp, SessionRecordingV2MetadataSwitchoverDate } from '../src/types'
import { safeClickhouseString } from '../src/utils/db/utils'
import {
    UUID,
    UUID7,
    UUIDT,
    bufferToStream,
    bufferToUint32ArrayLE,
    clickHouseTimestampToDateTime,
    cloneObject,
    createRandomUint32x4,
    escapeClickHouseString,
    getPropertyValueByPath,
    groupBy,
    sanitizeSqlIdentifier,
    stringify,
    uint32ArrayLEToBuffer,
} from '../src/utils/utils'

// .zip in Base64: github repo posthog/helloworldplugin
const zip =
    'UEsDBAoAAAAAAA8LbVEAAAAAAAAAAAAAAAAjAAkAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9VVAUAAc9Qrl9QSwMECgAAAAgADwttUQT7a+JUAAAAdQAAAC4ACQBoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uLy5wcmV0dGllcnJjVVQFAAHPUK5fq+ZSAAKlkqLEzJzMvHTn/NzcRCUrBaXUYlMlHahcYlJ4ZkpJBlDYBCpUnJqbCeSmJeYUp8KEgLpzUgNL80tSgTIlRaUwiYKizLwSmAGGRgZctVwAUEsDBAoAAAAIAA8LbVG/Zg9y6wAAAPMBAAArAAkAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9pbmRleC5qc1VUBQABz1CuX31RTUvEMBC951eMi5AUS1E8e9Sz4FFE0jjNBrKTkkxcZOl/N9u0hyo0hyHDe/PefOj0QwaGTIZdIEjIeXz12TpSFzCBBmdhauAioLySp+Cx88GqwxsyO7KQR+AjAqM+3Ryaf7yq0YhJCL31GmMwmNLzNxIrvMYWVs8WjDZFdWPNJWZijPAE+qwdV1JnkZVcINnC/dLEjKUttgrcwUMjZpoboJp3pZ8RIztMq+n1/cXe5RG9D/KjNCHPIfovucPtdZyZdaqupDvk27XPWjH/d+je9Z+UT/1SUNKXZbXqsa5gqiPGctRIVaHc4RdQSwMECgAAAAgADwttUVpiCFkvAAAAOQAAACkACQBoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL2xpYi5qc1VUBQABz1CuX0srzUsuyczPU8jJTHKDsTXySnOTUos0Faq5FICgKLWktChPASKooKVgZM1VywUAUEsDBAoAAAAIAA8LbVE7Twti+wAAAO0BAAAvAAkAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9wYWNrYWdlLmpzb25VVAUAAc9Qrl+VUbtOAzEQ7O8rjJHSQO6S9noEFEgUlGkud4vtyOe1dm1IFOXf8eNE0qazZ2ZnvONzI4R0wwyyF9IjB41qrcFa/EWy09rbqIyTz1n2A8QGXVZu2k27regEPJLxYWFeCSCIoEEUg4cqmgdTWOMmOLYHrmgd5ESc0zUBAThkGYwaxU6+ECH1wqHIhGAPo/k2MO2kWK0EHE0QW5kmL8WNIL3fBKTTjeHJl82UCSUyQZHsgjzpEDz3XZfOOu7bEefuM1Xwhqq7VlAbaLPDf9QQU0+Ubeoi1ozguCR9vH9VbB/VzWZL6h2JnWGOwNdQjTP4QcGdPo8Ew5T+t7k0f1BLAwQKAAAACAAPC21Ru8C8oc0AAABTAQAALgAJAGhlbGxvd29ybGRwbHVnaW4taW1hZ2VsZXNzLXZlcnNpb24vcGx1Z2luLmpzb25VVAUAAc9Qrl9tjz1rwzAQhnf/iquXLCHesxQytKVToEPms3WWr8g6VzqRL/LfKymQdOggxPu8zwvStQFoPc7UbqGdyDk5SnBmccmyb9elTcHVUnWJ266zrFPqN4PM3V6ifojt/t8ZikPgRVl82b8HIgWdCA7FBPQG3kQAYYdhDZ9fQIaL/HKfz8h1x97QafMd79RxX2C+HmgQP7LN9JpTzj2GR/jzucOEuorAvr4hS691Xh09L9WJGtjbJzc0YnJaqh4vTx7oJ3Egk4sRXaTKb005t+YXUEsBAgAACgAAAAAADwttUQAAAAAAAAAAAAAAACMACQAAAAAAAAAQAAAAAAAAAGhlbGxvd29ybGRwbHVnaW4taW1hZ2VsZXNzLXZlcnNpb24vVVQFAAHPUK5fUEsBAgAACgAAAAgADwttUQT7a+JUAAAAdQAAAC4ACQAAAAAAAQAAAAAASgAAAGhlbGxvd29ybGRwbHVnaW4taW1hZ2VsZXNzLXZlcnNpb24vLnByZXR0aWVycmNVVAUAAc9Qrl9QSwECAAAKAAAACAAPC21Rv2YPcusAAADzAQAAKwAJAAAAAAABAAAAAADzAAAAaGVsbG93b3JsZHBsdWdpbi1pbWFnZWxlc3MtdmVyc2lvbi9pbmRleC5qc1VUBQABz1CuX1BLAQIAAAoAAAAIAA8LbVFaYghZLwAAADkAAAApAAkAAAAAAAEAAAAAADACAABoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL2xpYi5qc1VUBQABz1CuX1BLAQIAAAoAAAAIAA8LbVE7Twti+wAAAO0BAAAvAAkAAAAAAAEAAAAAAK8CAABoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL3BhY2thZ2UuanNvblVUBQABz1CuX1BLAQIAAAoAAAAIAA8LbVG7wLyhzQAAAFMBAAAuAAkAAAAAAAEAAAAAAAAEAABoZWxsb3dvcmxkcGx1Z2luLWltYWdlbGVzcy12ZXJzaW9uL3BsdWdpbi5qc29uVVQFAAHPUK5fUEsFBgAAAAAGAAYATAIAACIFAAAoAGQ1YWExZDJiOGE1MzRmMzdjZDkzYmU0OGIyMTRmNDkwZWY5ZWU5MDQ='
const zipBuffer = Buffer.from(zip, 'base64')

describe('utils', () => {
    test('bufferToStream', () => {
        const stream = bufferToStream(zipBuffer)
        expect(stream.read()).toEqual(zipBuffer)
    })

    describe('bufferToBase64String and base64StringToUint32Array', () => {
        it('should be reversible with the empty array and empty string', () => {
            expect(bufferToUint32ArrayLE(uint32ArrayLEToBuffer(new Uint32Array(0)))).toEqual(new Uint32Array(0))
            expect(uint32ArrayLEToBuffer(bufferToUint32ArrayLE(zipBuffer))).toEqual(zipBuffer)
        })
        it('should be reversible with a random uint32x4', () => {
            const input = createRandomUint32x4()
            const base64 = uint32ArrayLEToBuffer(input)
            const output = bufferToUint32ArrayLE(base64)
            expect(output).toEqual(input)
        })
        it('should be reversible with a random buffer', () => {
            const input = randomBytes(16)
            const arr = bufferToUint32ArrayLE(input)
            const output = uint32ArrayLEToBuffer(arr)
            expect(output).toEqual(input)
        })
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

    describe('UUIDv7', () => {
        it('is well-formed', () => {
            const uuid7 = new UUID7()
            const uuid7String = uuid7.toString()
            // UTC timestamp matching (roughly, only comparing the beginning as the timestamp's end inevitably drifts away)
            expect(uuid7String.slice(0, 8)).toEqual(Date.now().toString(16).padStart(12, '0').slice(0, 8))
            // version digit matching
            expect(uuid7String[14]).toEqual('7')
            // var matching
            const variant = parseInt(uuid7String[19], 16) >>> 2
            expect(variant).toEqual(2)
        })
        it('has the correct value when given a timestamp and random bytes', () => {
            const timestamp = new Date('Wed, 30 Oct 2024 21:46:23 GMT').getTime()
            const randomBytes = Buffer.from(
                new Uint8Array([0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef, 0x01, 0x23])
            )
            const uuid7 = new UUID7(timestamp, randomBytes)
            expect(uuid7.toString()).toEqual('0192df64-df98-7123-8567-89abcdef0123')
        })
        it('can be loaded from a buffer', () => {
            const str = '0192df64df987123856789abcdef0123'
            const uuid = new UUID7(new Buffer(str, 'hex'))
            expect(uuid.toString().replace(/-/g, '')).toEqual(str)
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

            expect(() => groupBy(objects, 'i', true)).toThrow(
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

    describe('safeClickhouseString', () => {
        // includes real data
        const validStrings = [
            `$autocapture`,
            `correlation analyzed`,
            `docs_search_used`,
            `$$plugin_metrics`,
            `996f3e2f-830b-42f0-b2b8-df42bb7f7144`,
            `some?819)389**^371=2++211!!@==-''''..,,weird___id`,
            `form.form-signin:attr__action="/signup"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
            `a:attr__href="/signup"href="/signup"nth-child="1"nth-of-type="1"text="Create one here.";p:nth-child="8"nth-of-type="1";form.form-signin:attr__action="/login"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
            `input:nth-child="7"nth-of-type="3";form.form-signin:attr__action="/signup"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
            `a.nav-link:attr__class="nav-link"attr__href="/actions"href="/actions"nth-child="1"nth-of-type="1"text="Actions";li:nth-child="2"nth-of-type="2";ul.flex-sm-column.nav:attr__class="nav flex-sm-column"nth-child="1"nth-of-type="1";div.bg-light.col-md-2.col-sm-3.flex-shrink-1.pt-3.sidebar:attr__class="col-sm-3 col-md-2 sidebar flex-shrink-1 bg-light pt-3"attr__style="min-height: 100vh;"nth-child="1"nth-of-type="1";div.flex-column.flex-fill.flex-sm-row.row:attr__class="row flex-fill flex-column flex-sm-row"nth-child="1"nth-of-type="1";div.container-fluid.d-flex.flex-grow-1:attr__class="container-fluid flex-grow-1 d-flex"nth-child="1"nth-of-type="1";div:attr__id="root"attr_id="root"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
        ]

        test('does not modify valid strings', () => {
            for (const str of validStrings) {
                expect(safeClickhouseString(str)).toEqual(str)
            }
        })

        test('handles surrogate unicode characters correctly', () => {
            expect(safeClickhouseString(`foo \ud83d\ bar`)).toEqual(`foo \\ud83d\\ bar`)
            expect(safeClickhouseString(`\ud83d\ bar`)).toEqual(`\\ud83d\\ bar`)
            expect(safeClickhouseString(`\ud800\ \ud803\ `)).toEqual(`\\ud800\\ \\ud803\\ `)
        })

        test('does not modify non-surrogate unicode characters', () => {
            expect(safeClickhouseString(`✨`)).toEqual(`✨`)
            expect(safeClickhouseString(`foo \u2728\ bar`)).toEqual(`foo \u2728\ bar`)
            expect(safeClickhouseString(`💜 \u1f49c\ 💜`)).toEqual(`💜 \u1f49c\ 💜`)
        })
    })

    describe('clickHouseTimestampToDateTime()', () => {
        it('casts to a datetime', () => {
            expect(clickHouseTimestampToDateTime('2020-02-23 02:15:00.00' as ClickHouseTimestamp)).toEqual(
                DateTime.fromISO('2020-02-23T02:15:00.000Z').toUTC()
            )
        })
    })

    const january = () => new Date(Date.UTC(2025, 0, 1, 0, 0, 0))

    describe('parseSessionRecordingV2MetadataSwitchoverDate', () => {
        test.each([
            [null, null],
            ['*', true],
            ['2025-01-01', january()],
            ['2025-08-03T14:02:54+02:00', new Date(Date.UTC(2025, 7, 3, 12, 2, 54))],
        ])(
            'parseSessionRecordingV2MetadataSwitchoverDate: %s',
            (configValue: string | null, expected: Date | null | boolean) => {
                expect(parseSessionRecordingV2MetadataSwitchoverDate(configValue as string)).toEqual(expected)
            }
        )

        test.each([
            [123, null, false],
            [123, true, true],
            [january().getTime(), january(), true],
            // event is after the switchover
            [new Date(january().setHours(16)).getTime(), january(), true],
            // before
            [new Date(Date.UTC(2024, 11, 14)).getTime(), january(), false],
        ])(
            'eventPassesMetadataSwitchoverTest: %s',
            (eventTime: number, switchoverDate: Date | null | boolean, expected: boolean) => {
                expect(
                    eventPassesMetadataSwitchoverTest(
                        eventTime,
                        switchoverDate as SessionRecordingV2MetadataSwitchoverDate
                    )
                ).toEqual(expected)
            }
        )
    })
})

describe('getPropertyValueByPath', () => {
    it('returns primitive value when present', () => {
        expect(getPropertyValueByPath({ a: { b: 1 } }, ['a', 'b'])).toEqual(1)
    })
    it('returns object value when present', () => {
        expect(getPropertyValueByPath({ a: { b: 1 } }, ['a'])).toEqual({ b: 1 })
    })
    it('returns undefined when not present', () => {
        expect(getPropertyValueByPath({ a: { b: 1 } }, ['a', 'c'])).toEqual(undefined)
    })
    it('returns undefined when trying to access a property of a primitive', () => {
        expect(getPropertyValueByPath({ a: { b: 1 } }, ['a', 'b', 'c', 'd'])).toEqual(undefined)
    })
    it('returns value from array', () => {
        expect(getPropertyValueByPath({ a: { b: [1, 2, 3] } }, ['a', 'b', '1'])).toEqual(2)
    })
    it('requires at least one path key', () => {
        expect(() => getPropertyValueByPath({ a: { b: 'foo' } }, [])).toThrow('No path to property was provided')
    })
})
