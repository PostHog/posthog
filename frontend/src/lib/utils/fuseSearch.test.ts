import { createFuseSearch } from './fuseSearch'

describe('createFuseSearch', () => {
    interface Item {
        name: string
    }

    const items: Item[] = [
        { name: 'MCP server' },
        { name: 'Signed up' },
        { name: 'Map clicked' },
        { name: 'SMTP delivered' },
        { name: 'CMP accepted' },
        { name: 'Camp fire started' },
    ]

    const search = createFuseSearch<Item>(['name'])

    it.each([['mcp'], ['mcp '], [' mcp'], [' mcp '], ['mcp\t']])('returns only "MCP server" for query "%s"', (term) => {
        expect(search(items, term).map((i) => i.name)).toEqual(['MCP server'])
    })

    it.each([[''], ['   ']])('returns all items for empty or pure-whitespace query "%s"', (term) => {
        expect(search(items, term)).toEqual(items)
    })
})
