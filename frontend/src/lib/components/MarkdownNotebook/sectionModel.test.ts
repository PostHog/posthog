import {
    getMarkdownNotebookSectionRows,
    getMarkdownNotebookSections,
    getMarkdownNotebookVisualGroups,
    removeNotebookSection,
} from './documentModel'
import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'

const SECTION_A = '<Section title="Setup" />'
const SECTION_B = '<Section title="Analysis" />'
const SECTION_END = '<SectionEnd />'

function sectionSummaries(markdown: string): { title: string; collapsed: boolean; memberCount: number }[] {
    const { nodes } = parseMarkdownNotebook(markdown)
    return getMarkdownNotebookSections(nodes).map((section) => ({
        title: section.title,
        collapsed: section.collapsed,
        memberCount: section.memberEndIndex - section.startIndex - 1,
    }))
}

describe('markdown notebook sections', () => {
    // Markdown is the only storage, so every marker arrangement below can reach a real notebook —
    // a hand-edited document, a three-way merge that kept one side's marker, someone deleting half
    // a pair. Section derivation has to stay total: no arrangement may drop content or nest.
    it.each([
        [
            'a balanced pair',
            [SECTION_A, 'One', 'Two', SECTION_END].join('\n\n'),
            [{ title: 'Setup', collapsed: false, memberCount: 2 }],
        ],
        [
            'an unclosed section running to the end of the document',
            [SECTION_A, 'One', 'Two'].join('\n\n'),
            [{ title: 'Setup', collapsed: false, memberCount: 2 }],
        ],
        [
            'a second marker closing the first section instead of nesting inside it',
            [SECTION_A, 'One', SECTION_B, 'Two'].join('\n\n'),
            [
                { title: 'Setup', collapsed: false, memberCount: 1 },
                { title: 'Analysis', collapsed: false, memberCount: 1 },
            ],
        ],
        ['an end marker with nothing open', ['One', SECTION_END, 'Two'].join('\n\n'), []],
        [
            'a trailing end marker after the section already closed',
            [SECTION_A, 'One', SECTION_END, 'Two', SECTION_END].join('\n\n'),
            [{ title: 'Setup', collapsed: false, memberCount: 1 }],
        ],
        [
            'an untitled section holding nothing',
            ['<Section />', SECTION_END].join('\n\n'),
            [{ title: '', collapsed: false, memberCount: 0 }],
        ],
        [
            'a collapsed section',
            ['<Section title="Setup" collapsed />', 'One', SECTION_END].join('\n\n'),
            [{ title: 'Setup', collapsed: true, memberCount: 1 }],
        ],
    ])('derives sections from %s', (_, markdown, expected) => {
        expect(sectionSummaries(markdown)).toEqual(expected)
    })

    it('round-trips a section title and collapsed state through markdown', () => {
        const markdown = ['<Section title="Setup" collapsed />', 'One', SECTION_END].join('\n\n')

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
    })

    it('keeps cards after the end marker out of the section', () => {
        const { nodes } = parseMarkdownNotebook([SECTION_A, 'Inside', SECTION_END, 'Outside'].join('\n\n'))
        const rows = getMarkdownNotebookSectionRows(
            getMarkdownNotebookVisualGroups(nodes),
            getMarkdownNotebookSections(nodes)
        )

        expect(rows.map((row) => row.kind)).toEqual(['section', 'group'])
        expect(rows[0].kind === 'section' && rows[0].groups).toHaveLength(1)
    })

    it('renders an unmatched end marker as nothing rather than as a block of its own', () => {
        const { nodes } = parseMarkdownNotebook(['Before', SECTION_END, SECTION_A, 'Inside'].join('\n\n'))
        const rows = getMarkdownNotebookSectionRows(
            getMarkdownNotebookVisualGroups(nodes),
            getMarkdownNotebookSections(nodes)
        )

        expect(rows.map((row) => row.kind)).toEqual(['group', 'section'])
    })

    it('keeps every block a section held when the section is removed', () => {
        const { nodes } = parseMarkdownNotebook([SECTION_A, 'One', 'Two', SECTION_END, 'Outside'].join('\n\n'))
        const sectionNodeId = getMarkdownNotebookSections(nodes)[0].node.id

        const remainingNodes = removeNotebookSection(nodes, sectionNodeId)

        expect(serializeMarkdownNotebook({ type: 'doc', nodes: remainingNodes, errors: [] })).toEqual(
            ['One', 'Two', 'Outside'].join('\n\n')
        )
    })
})
