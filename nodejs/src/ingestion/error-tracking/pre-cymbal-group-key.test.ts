import { createTestPluginEvent } from '~/tests/helpers/plugin-event'

import { preCymbalGroupKey } from './pre-cymbal-group-key'

const exceptionEvent = (exception: Record<string, unknown>) =>
    createTestPluginEvent({ properties: { $exception_list: [exception] } })

describe('preCymbalGroupKey', () => {
    it('returns null when $exception_list is missing', () => {
        expect(preCymbalGroupKey(createTestPluginEvent())).toBeNull()
    })

    it('returns null when $exception_list is a non-array object with a numeric length', () => {
        const event = createTestPluginEvent({
            properties: { $exception_list: { length: 1 } as unknown as unknown[] },
        })
        expect(() => preCymbalGroupKey(event)).not.toThrow()
        expect(preCymbalGroupKey(event)).toBeNull()
    })

    it('does not throw when stacktrace.frames is a non-array object with a numeric length', () => {
        const event = createTestPluginEvent({
            properties: {
                $exception_list: [
                    {
                        type: 'TypeError',
                        value: 'boom',
                        stacktrace: { frames: { length: 1 } as unknown as unknown[] },
                    },
                ],
            },
        })
        expect(() => preCymbalGroupKey(event)).not.toThrow()
        expect(preCymbalGroupKey(event)).toMatch(/^[0-9a-f]{16}$/)
    })

    it('returns null when there is no message and no frames', () => {
        expect(preCymbalGroupKey(exceptionEvent({ type: 'Error' }))).toBeNull()
    })

    it('returns a 16-char hex digest', () => {
        const key = preCymbalGroupKey(exceptionEvent({ type: 'Error', value: 'boom' }))
        expect(key).toMatch(/^[0-9a-f]{16}$/)
    })

    describe('message-only exceptions', () => {
        it('groups by type and value', () => {
            const a = preCymbalGroupKey(exceptionEvent({ type: 'TypeError', value: 'same' }))
            const b = preCymbalGroupKey(exceptionEvent({ type: 'TypeError', value: 'same' }))
            const c = preCymbalGroupKey(exceptionEvent({ type: 'TypeError', value: 'other' }))

            expect(a).toBe(b)
            expect(a).not.toBe(c)
        })

        it('does not collide when separator-like chars appear in type or value', () => {
            // A naive `${type}|${value}` join would hash both of these to "A|B|C".
            const typeShifted = preCymbalGroupKey(exceptionEvent({ type: 'A|B', value: 'C' }))
            const valueShifted = preCymbalGroupKey(exceptionEvent({ type: 'A', value: 'B|C' }))
            expect(typeShifted).not.toBe(valueShifted)
        })
    })

    describe('stack exceptions', () => {
        const stackEvent = (fn: string, value: string = 'msg') =>
            exceptionEvent({
                type: 'TypeError',
                value,
                stacktrace: {
                    frames: [{ function: fn, filename: `${fn}.js`, lineno: 1 }],
                },
            })

        it('groups by stack and ignores message when frames exist', () => {
            const a = preCymbalGroupKey(stackEvent('foo'))
            const b = preCymbalGroupKey(stackEvent('foo', 'different'))

            expect(a).toBe(b)
        })

        it('separates different stacks', () => {
            expect(preCymbalGroupKey(stackEvent('foo'))).not.toBe(preCymbalGroupKey(stackEvent('bar')))
        })

        it('does not conflate adjacent empty fields across frame boundaries', () => {
            const split = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [
                            { function: 'a', filename: 'bc' },
                            { function: '', filename: '' },
                        ],
                    },
                })
            )
            const merged = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [{ function: 'a', filename: 'bc' }],
                    },
                })
            )

            expect(split).not.toBe(merged)
        })

        it('uses abs_path, line, and column aliases', () => {
            const withAliases = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [{ function: 'fn', abs_path: '/app/x.js', line: 10, column: 2 }],
                    },
                })
            )
            const withCanonical = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [{ function: 'fn', filename: '/app/x.js', lineno: 10, colno: 2 }],
                    },
                })
            )

            expect(withAliases).toBe(withCanonical)
        })

        it('does not throw when a frame is null', () => {
            expect(() =>
                preCymbalGroupKey(
                    exceptionEvent({
                        type: 'Error',
                        stacktrace: { frames: [{ function: 'a' }, null] },
                    })
                )
            ).not.toThrow()
        })

        it('treats an invalid frame as empty fields without conflating it with the next valid frame', () => {
            const withNull = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: { frames: [null, { function: 'a' }] },
                })
            )
            const onlyValid = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: { frames: [{ function: 'a' }] },
                })
            )
            expect(withNull).not.toBe(onlyValid)
        })

        it('ignores extra frame properties', () => {
            const minimal = preCymbalGroupKey(stackEvent('fn'))
            const verbose = preCymbalGroupKey(
                exceptionEvent({
                    type: 'TypeError',
                    value: 'msg',
                    stacktrace: {
                        frames: [
                            {
                                function: 'fn',
                                filename: 'fn.js',
                                lineno: 1,
                                context_line: 'const x = 1',
                                vars: { x: 1 },
                            },
                        ],
                    },
                })
            )

            expect(minimal).toBe(verbose)
        })
    })

    describe('chained exceptions', () => {
        const chainedEvent = (excs: unknown[]) => createTestPluginEvent({ properties: { $exception_list: excs } })

        it('separates chains that share a wrapper but have different root causes', () => {
            const sameCause = chainedEvent([
                { type: 'WrapperError', value: 'wrap' },
                { type: 'TypeError', value: 'cause-A' },
            ])
            const differentCause = chainedEvent([
                { type: 'WrapperError', value: 'wrap' },
                { type: 'TypeError', value: 'cause-B' },
            ])

            expect(preCymbalGroupKey(sameCause)).not.toBe(preCymbalGroupKey(differentCause))
        })

        it('groups chains whose every exception matches', () => {
            const make = () =>
                chainedEvent([
                    { type: 'WrapperError', value: 'wrap' },
                    { type: 'TypeError', value: 'cause' },
                ])
            expect(preCymbalGroupKey(make())).toBe(preCymbalGroupKey(make()))
        })

        it('skips null entries in the chain without throwing', () => {
            const key = preCymbalGroupKey(chainedEvent([{ type: 'TypeError', value: 'real' }, null]))
            expect(key).toMatch(/^[0-9a-f]{16}$/)
        })
    })
})
