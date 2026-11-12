import { SEALED_PROTOTYPES } from './seal-intrinsics'

describe('seal-intrinsics', () => {
    it.each([
        ['__proto__ of an object', (target: any) => target['__proto__']],
        ['constructor.prototype of an object', (target: any) => target['constructor']['prototype']],
        ['__proto__ of an array', () => ([] as any)['__proto__']],
        ['__proto__ of a function', () => (((): void => {}) as any)['__proto__']],
    ])('rejects a new key written through %s', (_, reach) => {
        expect(() => {
            reach({})['pollutedKey'] = 'value'
        }).toThrow(TypeError)
        expect(({} as any).pollutedKey).toBeUndefined()
    })

    it('seals every listed prototype', () => {
        expect(SEALED_PROTOTYPES.every((prototype) => Object.isSealed(prototype))).toBe(true)
    })
})
