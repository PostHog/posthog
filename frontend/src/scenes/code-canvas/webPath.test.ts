import { webPath } from './webPath'

describe('webPath', () => {
    it.each([
        ['a project prefix', '/project/123/code/canvas/ch-1/c-1', '/project/123/canvases/c-1'],
        ['no project', '/code/canvas/ch-1/c-1', '/canvases/c-1'],
        ['a project that is not an id', '/project/@current/code/canvas/ch-1/c-1', '/canvases/c-1'],
    ])('builds the web path for a link with %s', (_, linkPathname, expected) => {
        expect(webPath(linkPathname, '/canvases/c-1')).toBe(expected)
    })
})
