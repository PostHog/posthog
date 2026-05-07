import { BACKLINK_MAP } from './NotebookNodeBacklink'

const stripQueryAndHash = (path: string): string => path.split(/[?#]/)[0]

describe('NotebookNodeBacklink BACKLINK_MAP', () => {
    const findConfig = (type: string): (typeof BACKLINK_MAP)[number] => {
        const config = BACKLINK_MAP.find((c) => c.type === type)
        if (!config) {
            throw new Error(`No BACKLINK_MAP entry for type "${type}"`)
        }
        return config
    }

    describe('notebooks', () => {
        const notebooks = findConfig('notebooks')

        it.each([
            ['no project prefix', '/notebooks/abc123', 'abc123'],
            ['with project prefix', '/project/2/notebooks/abc123', 'abc123'],
            ['with query string', '/notebooks/abc123?source=share', 'abc123'],
            ['with hash', '/notebooks/abc123#section', 'abc123'],
            ['project prefix and query string', '/project/2/notebooks/abc123?foo=bar', 'abc123'],
        ])('extracts the short_id from path with %s', (_label, path, expectedId) => {
            const stripped = stripQueryAndHash(path)
            expect(notebooks.regex.test(stripped)).toBe(true)
            expect(notebooks.regex.exec(stripped)?.[1]).toBe(expectedId)
        })
    })

    describe('dashboards', () => {
        const dashboards = findConfig('dashboards')

        it.each([
            ['no project prefix', '/dashboard/4', '4'],
            ['with project prefix', '/project/2/dashboard/4', '4'],
        ])('extracts the dashboard id from path with %s', (_label, path, expectedId) => {
            const stripped = stripQueryAndHash(path)
            expect(dashboards.regex.test(stripped)).toBe(true)
            expect(dashboards.regex.exec(stripped)?.[1]).toBe(expectedId)
        })
    })

    describe('feature_flags', () => {
        const flags = findConfig('feature_flags')

        it('extracts the flag id when path includes a project prefix', () => {
            expect(flags.regex.exec('/project/2/feature_flags/42')?.[1]).toBe('42')
        })
    })
})
