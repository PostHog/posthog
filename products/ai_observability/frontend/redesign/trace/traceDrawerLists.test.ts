import { TRACE_DRAWER_LISTS, TraceDrawerListId, traceDrawerBackLabel } from './traceDrawerLists'

describe('entity trace drawer lists', () => {
    it.each([
        ['error-traces', '/ai-observability/errors', 'errors', 'Back to errors'],
        ['tool-traces', '/ai-observability/tools', 'tools', 'Back to tools'],
        ['person-traces', '/ai-observability/users', 'people', 'Back to people'],
    ] as [TraceDrawerListId, string, string, string][])('%s owns %s', (id, path, backTo, backLabel) => {
        const list = TRACE_DRAWER_LISTS[id]
        expect(list.pathMatcher.test(path)).toBe(true)
        expect(list.pathMatcher.test(`${path}/extra`)).toBe(false)
        expect(list.rowClick).toBe(false)
        expect(list.showNavigation).toBe(true)
        expect(list.backTo).toBe(backTo)
        expect(traceDrawerBackLabel(backTo)).toBe(backLabel)
    })
})
