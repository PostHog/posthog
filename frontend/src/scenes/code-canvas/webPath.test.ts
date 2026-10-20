import { webPath } from './webPath'

describe('webPath', () => {
    it.each([
        ['a numeric project', 123, '/project/123/canvases/c-1'],
        ['a numeric string project', '123', '/project/123/canvases/c-1'],
        ['no project', undefined, '/canvases/c-1'],
        ['a project that is not an id', '../admin', '/canvases/c-1'],
    ])('builds the web path for %s', (_, project, expected) => {
        expect(webPath(project, '/canvases/c-1')).toBe(expected)
    })
})
