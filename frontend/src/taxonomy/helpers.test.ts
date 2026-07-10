import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { filterExactSearchOnlyItems } from './helpers'

describe('filterExactSearchOnlyItems', () => {
    // `mcp init` is flagged `only_shown_on_exact_search` in the taxonomy; the canonical
    // `$mcp_tool_call` and `$pageview` are not.
    const items = [{ name: 'mcp init' }, { name: '$mcp_tool_call' }, { name: '$pageview' }]
    const run = (query: string): string[] =>
        filterExactSearchOnlyItems(items, (i) => i.name, TaxonomicFilterGroupType.Events, query).map((i) => i.name)

    const cases: [string, string, string[]][] = [
        ['no query hides the legacy event', '', ['$mcp_tool_call', '$pageview']],
        ['fuzzy match hides the legacy event', 'mcp', ['$mcp_tool_call', '$pageview']],
        ['exact name keeps the legacy event', 'mcp init', ['mcp init', '$mcp_tool_call', '$pageview']],
        ['exact name is case-insensitive', 'MCP INIT', ['mcp init', '$mcp_tool_call', '$pageview']],
        ['exact label keeps the legacy event', 'MCP init (legacy)', ['mcp init', '$mcp_tool_call', '$pageview']],
    ]

    it.each(cases)('%s', (_label, query, expected) => {
        expect(run(query)).toEqual(expected)
    })
})
