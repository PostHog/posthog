import { frameSourceFileName } from './frameSourceFileName'

describe('frameSourceFileName', () => {
    it.each([
        ['a plain path', 'app/routes/order.tsx', 'order.tsx'],
        ['a React Router route chunk', 'app/routes/order.tsx?route-chunk=clientAction', 'order.tsx'],
        ['a query that contains a slash', 'app/routes/order.tsx?route-chunk=a/b', 'order.tsx'],
        ['a webpack hash', 'webpack:///./src/folder/ui/select.vue?821e', 'select.vue'],
        ['a Vue block query', 'src/App.vue?vue&type=script&setup=true&lang.ts', 'App.vue'],
        ['a fragment', 'src/main.ts#L10', 'main.ts'],
    ])('names the file for %s', (_label, source, expected) => {
        expect(frameSourceFileName(source)).toBe(expected)
    })

    it.each([
        ['an empty path', ''],
        ['a directory', 'app/routes/'],
        ['only a query', '?raw'],
    ])('names no file for %s', (_label, source) => {
        expect(frameSourceFileName(source)).toBeUndefined()
    })
})
