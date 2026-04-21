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

    it('returns only the exact match for "mcp"', () => {
        expect(search(items, 'mcp').map((i) => i.name)).toEqual(['MCP server'])
    })

    it.each([['mcp '], [' mcp'], [' mcp '], ['mcp\t']])(
        'treats "%s" the same as "mcp" (trailing/leading whitespace must not broaden matching)',
        (padded) => {
            expect(search(items, padded).map((i) => i.name)).toEqual(['MCP server'])
        }
    )

    it('returns all items when term is empty or pure whitespace', () => {
        expect(search(items, '')).toEqual(items)
        expect(search(items, '   ')).toEqual(items)
    })
})
