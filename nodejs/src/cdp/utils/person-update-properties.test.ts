import { register } from 'prom-client'

import { compileHog } from '../templates/compiler'
import {
    PersonUpdatePropertyOutcome,
    PersonUpdatePropertyRead,
    bytecodePersonUpdatePropertyReads,
    findPersonUpdatePropertyReads,
    inputsPersonUpdatePropertyReads,
    personUpdatePropertyReadOutcome,
    trackPersonUpdatePropertyReads,
} from './person-update-properties'

describe('person update properties', () => {
    const read = (path: string[]): PersonUpdatePropertyRead => ({ key: '$set', path })

    describe('findPersonUpdatePropertyReads', () => {
        // Compiled against the real compiler so a change to how it emits global chains surfaces
        // here, rather than as a scanner that silently stops finding anything.
        it.each<[string, string, PersonUpdatePropertyRead[]]>([
            [
                'a nested read off event properties',
                'return event.properties.$set.email',
                [{ key: '$set', path: ['email'] }],
            ],
            [
                'a nested read off filter globals',
                'return properties.$set_once.plan',
                [{ key: '$set_once', path: ['plan'] }],
            ],
            [
                'the whole path of a deeply nested read',
                'return event.properties.$set.profile.name',
                [{ key: '$set', path: ['profile', 'name'] }],
            ],
            ['a whole object read, with no path', 'return event.properties.$set', [{ key: '$set', path: [] }]],
            [
                'both keys in one program',
                'return f(event.properties.$set.email, event.properties.$set_once.plan)',
                [
                    { key: '$set', path: ['email'] },
                    { key: '$set_once', path: ['plan'] },
                ],
            ],
            ['nothing for unrelated properties', 'return event.properties.$browser', []],
            ['nothing for a $set key outside properties', 'return event.$set.email', []],
            ['nothing for a person property of the same name', 'return person.properties.$set.email', []],
            // Only globals compile to a single chain, so a read through a local is invisible here.
            ['nothing for a read through a local variable', 'let p := event.properties\nreturn p.$set.email', []],
        ])('finds %s', async (_name, hog, expected) => {
            expect(findPersonUpdatePropertyReads(await compileHog(hog))).toEqual(expected)
        })
    })

    describe('inputsPersonUpdatePropertyReads', () => {
        it('finds reads nested inside a compiled input tree', async () => {
            const hogFunction = {
                inputs: {
                    payload: {
                        value: {},
                        bytecode: { body: { email: await compileHog('return event.properties.$set.email') } },
                    },
                },
                mappings: [
                    {
                        inputs: {
                            plan: { value: '', bytecode: await compileHog('return event.properties.$set.plan') },
                        },
                    },
                ],
            } as any

            expect(inputsPersonUpdatePropertyReads(hogFunction)).toEqual([
                { key: '$set', path: ['email'] },
                { key: '$set', path: ['plan'] },
            ])
        })

        it('memoizes per function so every invocation does not rescan', async () => {
            const hogFunction = {
                inputs: { payload: { value: '', bytecode: await compileHog('return event.properties.$set.email') } },
            } as any

            expect(inputsPersonUpdatePropertyReads(hogFunction)).toBe(inputsPersonUpdatePropertyReads(hogFunction))
        })
    })

    describe('bytecodePersonUpdatePropertyReads', () => {
        it.each([[null], [undefined], ['not bytecode'], [{}]])('tolerates %p', (bytecode) => {
            expect(bytecodePersonUpdatePropertyReads(bytecode)).toEqual([])
        })
    })

    describe('personUpdatePropertyReadOutcome', () => {
        it.each<[PersonUpdatePropertyOutcome, PersonUpdatePropertyRead, any, any]>([
            ['mappable', read(['email']), { $set: { email: 'a@example.com' } }, { email: 'a@example.com' }],
            ['value_differs', read(['email']), { $set: { email: 'a@example.com' } }, { email: 'b@example.com' }],
            ['missing_on_person', read(['email']), { $set: { email: 'a@example.com' } }, { plan: 'paid' }],
            ['absent_in_event', read(['email']), { $set: { plan: 'paid' } }, { email: 'a@example.com' }],
            ['absent_in_event', read(['email']), {}, { email: 'a@example.com' }],
            ['no_person', read(['email']), { $set: { email: 'a@example.com' } }, undefined],
            ['whole_object', read([]), { $set: { email: 'a@example.com' } }, { email: 'a@example.com' }],
            ['mappable', read(['profile']), { $set: { profile: { name: 'Ada' } } }, { profile: { name: 'Ada' } }],
            ['value_differs', read(['profile']), { $set: { profile: { name: 'Ada' } } }, { profile: { name: 'Bo' } }],
            // A falsy value the event really set is a value, not an absence.
            ['mappable', read(['count']), { $set: { count: 0 } }, { count: 0 }],
            ['mappable', read(['optedIn']), { $set: { optedIn: false } }, { optedIn: false }],
        ])('reports %s', (expected, subject, eventProperties, personProperties) => {
            expect(personUpdatePropertyReadOutcome(subject, eventProperties, personProperties)).toEqual(expected)
        })

        it('walks a nested path on both sides', () => {
            expect(
                personUpdatePropertyReadOutcome(
                    read(['profile', 'name']),
                    { $set: { profile: { name: 'Ada' } } },
                    { profile: { name: 'Ada' } }
                )
            ).toEqual('mappable')
        })
    })

    // This module runs inside the filter and executor paths, where a throw does not mean "tracking
    // failed": during filtering it reads as "the event does not match", which would silently stop a
    // destination firing. So no input may make an entry point throw.
    describe('never throws', () => {
        const hostile = () => {
            const throwingGetter = {}
            Object.defineProperty(throwingGetter, 'email', {
                get: () => {
                    throw new Error('property access exploded')
                },
                enumerable: true,
            })

            // Two distinct objects, so the comparison cannot short-circuit on identity and has to
            // reach the serialization that a cycle breaks.
            const circular = () => {
                const value: Record<string, any> = { profile: {} }
                value.profile.self = value
                return value
            }

            return { throwingGetter, circular }
        }

        const errorCount = async (): Promise<number> => {
            const metric = await register.getSingleMetric('cdp_person_update_property_error')?.get()
            return (metric?.values ?? []).reduce((total, sample) => total + sample.value, 0)
        }

        it('survives a person property whose getter throws, and reports it', async () => {
            const { throwingGetter } = hostile()
            const before = await errorCount()

            expect(() =>
                trackPersonUpdatePropertyReads({
                    reads: [read(['email'])],
                    source: 'hog',
                    functionType: 'destination',
                    eventProperties: { $set: { email: 'a@example.com' } },
                    personProperties: throwingGetter,
                })
            ).not.toThrow()

            // Proves the guard caught something rather than the input being harmless, and that a
            // failure is visible instead of silent.
            expect(await errorCount()).toBeGreaterThan(before)
        })

        it('survives an event property whose getter throws', () => {
            const { throwingGetter } = hostile()

            expect(() =>
                trackPersonUpdatePropertyReads({
                    reads: [read(['email'])],
                    source: 'filters',
                    functionType: 'destination',
                    eventProperties: { $set: throwingGetter },
                    personProperties: { email: 'a@example.com' },
                })
            ).not.toThrow()
        })

        it('survives a circular value on both sides of the comparison', () => {
            const { circular } = hostile()

            expect(() =>
                trackPersonUpdatePropertyReads({
                    reads: [read(['profile'])],
                    source: 'inputs',
                    functionType: 'destination',
                    eventProperties: { $set: circular() },
                    personProperties: circular(),
                })
            ).not.toThrow()
        })

        it.each([
            ['bytecode of the wrong shape', [1, 'GET_GLOBAL', {}, null, undefined, Symbol('x')]],
            ['a chain length past the start of the program', [32, 'email', 1, 99]],
            ['a chain length that is not a number', [32, 'email', 1, 'four']],
        ])('survives %s', (_name, bytecode) => {
            expect(() => findPersonUpdatePropertyReads(bytecode)).not.toThrow()
        })

        it('survives an input tree deeper than the walk allows', () => {
            let deep: Record<string, any> = { bytecode: ['_H', 1] }
            for (let level = 0; level < 500; level++) {
                deep = { nested: deep }
            }

            expect(() => inputsPersonUpdatePropertyReads({ inputs: { payload: deep } } as any)).not.toThrow()
        })

        it('survives inputs that are not the shape it expects', () => {
            expect(() =>
                inputsPersonUpdatePropertyReads({ inputs: 'not an object', mappings: 'neither' } as any)
            ).not.toThrow()
        })
    })
})
