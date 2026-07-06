import { parseMarkdownNotebook, serializeMarkdownNotebook, serializeNode } from './markdown'
import {
    NotebookBlockNode,
    NotebookDocument,
    NotebookInlineMark,
    NotebookInlineNode,
    NotebookListBlockNode,
    NotebookTableBlockNode,
    NotebookTextBlockNode,
} from './types'
import { getInlineText, getNodeText } from './utils'

function makeDocument(nodes: NotebookBlockNode[]): NotebookDocument {
    return { type: 'doc', nodes, errors: [] }
}

function roundTrip(document: NotebookDocument): NotebookDocument {
    return parseMarkdownNotebook(serializeMarkdownNotebook(document))
}

function stripIds(document: NotebookDocument): unknown {
    return document.nodes.map((node) => {
        const { id: _id, ...rest } = node
        if (node.type === 'list') {
            return {
                ...rest,
                items: node.items.map(({ id: _itemId, ...item }) => item),
            }
        }
        return rest
    })
}

function textContent(document: NotebookDocument): string {
    return document.nodes
        .filter((node) => node.type !== 'component')
        .map(getNodeText)
        .join('\n')
}

function paragraph(children: NotebookInlineNode[]): NotebookTextBlockNode {
    return { id: '', type: 'paragraph', children }
}

function text(value: string, marks?: NotebookInlineMark[]): NotebookInlineNode {
    return { type: 'text', text: value, marks }
}

// Deterministic LCG so failures are reproducible
function makeRandom(seed: number): () => number {
    let state = seed
    return () => {
        state = (state * 1664525 + 1013904223) >>> 0
        return state / 0x100000000
    }
}

const TEXT_PIECES = [
    'hello world',
    'a*b',
    '**not bold**',
    '`not code`',
    'user_id',
    '_not italic_',
    '#tag',
    '- not a list',
    '1. not ordered',
    '[x] not a task',
    '[ ] also not a task',
    '| not | a | table |',
    '<Important note',
    '```',
    'back\\slash',
    '~~not struck~~',
    '[not](a-link)',
    'emoji 🦔 test',
    'naïve café',
    '日本語のテキスト',
    'paren ) here',
]

const CODE_LINES = ['const a = 1', '', '```', '```js', 'x `y` z', '    indented', 'done']

const LINK_HREFS = ['https://posthog.com/docs', 'https://en.wikipedia.org/wiki/Hog_(disambiguation)']

const MARK_CHOICES: NotebookInlineMark[][] = [
    [],
    [{ type: 'bold' }],
    [{ type: 'italic' }],
    [{ type: 'bold' }, { type: 'italic' }],
    [{ type: 'strike' }],
    [{ type: 'underline' }],
    [{ type: 'code' }],
    [{ type: 'bold' }, { type: 'code' }],
]

describe('markdown round trip', () => {
    describe('generated documents', () => {
        const random = makeRandom(42)
        const pick = <T>(items: T[]): T => items[Math.floor(random() * items.length)]
        const count = (max: number): number => 1 + Math.floor(random() * max)

        const makeInlineRun = (allowLink: boolean): NotebookInlineNode => {
            const marks = [...pick(MARK_CHOICES)]
            if (allowLink && random() < 0.2) {
                marks.push({ type: 'link', href: pick(LINK_HREFS) })
            }
            const value = Array.from({ length: count(2) }, () => pick(TEXT_PIECES)).join(' ')
            return text(value, marks.length ? marks : undefined)
        }

        const makeInlineChildren = (allowHardBreaks: boolean): NotebookInlineNode[] => {
            const children: NotebookInlineNode[] = []
            const runs = count(3)
            for (let runIndex = 0; runIndex < runs; runIndex++) {
                if (runIndex > 0 && allowHardBreaks && random() < 0.3) {
                    children.push({ type: 'hardBreak' })
                }
                children.push(makeInlineRun(true))
            }
            return children
        }

        const makeNode = (): NotebookBlockNode => {
            const roll = random()
            if (roll < 0.35) {
                return paragraph(makeInlineChildren(true))
            }
            if (roll < 0.45) {
                return {
                    id: '',
                    type: 'heading',
                    level: count(6) as NotebookTextBlockNode['level'],
                    children: [makeInlineRun(false)],
                }
            }
            if (roll < 0.55) {
                return { id: '', type: 'blockquote', children: makeInlineChildren(true) }
            }
            if (roll < 0.68) {
                const ordered = random() < 0.5
                let previousDepth = 0
                const items: NotebookListBlockNode['items'] = Array.from({ length: count(4) }, (_, itemIndex) => {
                    const depth = itemIndex === 0 ? 0 : Math.max(0, previousDepth + Math.floor(random() * 3) - 1)
                    previousDepth = depth
                    return {
                        id: '',
                        children: [makeInlineRun(false)],
                        depth,
                        ordered,
                        start: ordered ? 1 : undefined,
                        checked: !ordered && random() < 0.3 ? random() < 0.5 : undefined,
                    }
                })
                return { id: '', type: 'list', ordered, start: ordered ? 1 : undefined, items }
            }
            if (roll < 0.78) {
                return {
                    id: '',
                    type: 'code',
                    language: pick([undefined, 'js', 'python']),
                    text: Array.from({ length: count(5) }, () => pick(CODE_LINES)).join('\n'),
                }
            }
            if (roll < 0.88) {
                const columnCount = count(3)
                const makeRow = (): NotebookTableBlockNode['rows'][number] =>
                    Array.from({ length: columnCount }, () => ({ children: [makeInlineRun(false)] }))
                return {
                    id: '',
                    type: 'table',
                    headers: makeRow(),
                    rows: Array.from({ length: count(2) }, makeRow),
                    alignments: [],
                }
            }
            if (roll < 0.94) {
                return { id: '', type: 'component', tagName: 'Divider', props: {} }
            }
            return {
                id: '',
                type: 'component',
                tagName: 'Query',
                props: {
                    query: { kind: 'TrendsQuery', series: [1, 'a'] },
                    title: 'He said "hi" — with *specials*',
                },
            }
        }

        it('preserves text content and reaches a serialization fixpoint', () => {
            expect.hasAssertions()
            for (let documentIndex = 0; documentIndex < 300; documentIndex++) {
                const generated = makeDocument(Array.from({ length: count(7) }, makeNode))
                const onceParsed = roundTrip(generated)
                const twiceParsed = roundTrip(onceParsed)

                // No content may be lost or invented by serialize→parse
                expect(textContent(onceParsed)).toEqual(textContent(generated))
                expect(onceParsed.errors).toEqual([])
                // After one normalization pass the representation must be stable
                expect(stripIds(twiceParsed)).toEqual(stripIds(onceParsed))
            }
        })
    })

    describe('literal markdown syntax in text', () => {
        it.each([
            'use **bold** syntax and `backticks` here',
            'multiply 3 * 4 * 5 and 2*3',
            'snake_case and _underscores_ and __dunder__',
            'brackets [x] and [label](target) inline',
            'tildes ~~struck~~ and single ~ tilde',
            'underline <u>tags</u> stay literal',
            'pipes | in | prose',
            'back\\slash and \\* escaped star',
        ])('round-trips %j as literal paragraph text', (value) => {
            const document = makeDocument([paragraph([text(value)])])
            const result = roundTrip(document)

            expect(result.nodes).toHaveLength(1)
            expect(result.nodes[0].type).toEqual('paragraph')
            expect(getNodeText(result.nodes[0])).toEqual(value)
        })

        it.each([
            '# looks like a heading',
            '## another heading',
            '> looks like a quote',
            '- looks like a bullet',
            '+ plus bullet',
            '• unicode bullet',
            '1. looks ordered',
            '12) also ordered',
            '---',
            '-----',
            '<Important> remember this',
            '```',
        ])('keeps a paragraph starting with %j a paragraph', (value) => {
            const document = makeDocument([paragraph([text(value)]), paragraph([text('second block')])])
            const result = roundTrip(document)

            expect(result.nodes.map((node) => node.type)).toEqual(['paragraph', 'paragraph'])
            expect(getNodeText(result.nodes[0])).toEqual(value)
        })

        it('keeps block-looking text after a hard break inside a paragraph', () => {
            const document = makeDocument([
                paragraph([text('first line'), { type: 'hardBreak' }, text('- not a bullet')]),
            ])
            const result = roundTrip(document)

            expect(result.nodes).toHaveLength(1)
            expect(getNodeText(result.nodes[0])).toEqual('first line\n- not a bullet')
        })
    })

    describe('unclosed component tags', () => {
        it('does not swallow the rest of the document', () => {
            const markdown = '# Title\n\n<Important config\n\nThis text must survive\n\n## And this heading'
            const document = parseMarkdownNotebook(markdown)

            expect(document.errors.map((error) => error.message)).toEqual(['Unclosed component tag'])
            expect(document.nodes.map((node) => node.type)).toEqual(['heading', 'paragraph', 'paragraph', 'heading'])
            expect(getNodeText(document.nodes[1])).toEqual('<Important config')
            expect(getNodeText(document.nodes[2])).toEqual('This text must survive')
        })

        it('keeps the raw source of a component tag with malformed props through serialization', () => {
            const markdown = '<Broken "unparseable />\n\nnext paragraph'
            const document = parseMarkdownNotebook(markdown)

            const componentNode = document.nodes[0]
            expect(componentNode.type).toEqual('component')
            expect(componentNode.type === 'component' && componentNode.errors?.length).toBeTruthy()
            // The malformed source must survive the next save instead of collapsing to `<Broken />`
            expect(serializeMarkdownNotebook(document)).toEqual(markdown)
            expect(getNodeText(document.nodes[1])).toEqual('next paragraph')
        })

        it('round-trips the fallback paragraph without re-parsing it as a component', () => {
            const first = parseMarkdownNotebook('<Important note\n\nbody text')
            const second = roundTrip(first)

            expect(second.errors).toEqual([])
            expect(textContent(second)).toEqual(textContent(first))
        })
    })

    describe('html comments', () => {
        it('parses a standalone comment line into a Comment node', () => {
            const document = parseMarkdownNotebook('# Title\n\n<!-- reviewer note -->\n\nBody')

            expect(document.errors).toEqual([])
            expect(document.nodes.map((node) => node.type)).toEqual(['heading', 'component', 'paragraph'])
            const commentNode = document.nodes[1]
            expect(commentNode.type === 'component' && commentNode.tagName).toEqual('Comment')
            expect(commentNode.type === 'component' && commentNode.props.text).toEqual('reviewer note')
        })

        it('round-trips a comment back to plain markdown without ids or markup noise', () => {
            const markdown = '# Title\n\n<!-- reviewer note -->\n\nBody'
            expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
        })

        it('parses multi-line comments, including blank lines', () => {
            const document = parseMarkdownNotebook('<!-- first line\n\nsecond line -->\n\nBody')

            const commentNode = document.nodes[0]
            expect(commentNode.type === 'component' && commentNode.props.text).toEqual('first line\n\nsecond line')
            expect(getNodeText(document.nodes[1])).toEqual('Body')
            expect(serializeMarkdownNotebook(document)).toEqual('<!-- first line\n\nsecond line -->\n\nBody')
        })

        it('splits a comment line off a preceding paragraph', () => {
            const document = parseMarkdownNotebook('Some text\n<!-- aside -->')

            expect(document.nodes.map((node) => node.type)).toEqual(['paragraph', 'component'])
            expect(getNodeText(document.nodes[0])).toEqual('Some text')
        })

        it('keeps an unclosed comment as a paragraph instead of swallowing the document', () => {
            const document = parseMarkdownNotebook('<!-- never closed\n\nThis text must survive')

            expect(document.nodes.map((node) => node.type)).toEqual(['paragraph', 'paragraph'])
            expect(getNodeText(document.nodes[1])).toEqual('This text must survive')
        })

        it('keeps a comment with trailing content on the closing line as a paragraph', () => {
            const document = parseMarkdownNotebook('<!-- aside --> trailing text')

            expect(document.nodes.map((node) => node.type)).toEqual(['paragraph'])
            expect(getNodeText(document.nodes[0])).toEqual('<!-- aside --> trailing text')
        })

        it('escapes paragraph lines that would otherwise re-parse as comments', () => {
            const document = makeDocument([paragraph([text('<!-- not a comment -->')])])
            const reparsed = roundTrip(document)

            expect(reparsed.nodes.map((node) => node.type)).toEqual(['paragraph'])
            expect(getNodeText(reparsed.nodes[0])).toEqual('<!-- not a comment -->')
        })

        it('neutralizes a premature closing marker inside the comment text', () => {
            const document = parseMarkdownNotebook('<!-- note -->')
            const commentNode = document.nodes[0]
            if (commentNode.type !== 'component') {
                throw new Error('expected a component node')
            }

            const serialized = serializeNode({ ...commentNode, props: { text: 'evil --> breakout' } })
            const reparsed = parseMarkdownNotebook(serialized)
            expect(reparsed.nodes).toHaveLength(1)
            expect(reparsed.nodes[0].type).toEqual('component')
        })
    })

    describe('code blocks containing fences', () => {
        it('uses a fence longer than any backtick run in the content', () => {
            const node: NotebookBlockNode = {
                id: '',
                type: 'code',
                language: 'md',
                text: 'Example:\n```js\nconst a = 1\n```\ndone',
            }

            expect(serializeNode(node)).toEqual('````md\nExample:\n```js\nconst a = 1\n```\ndone\n````')
        })

        it('uses a longer fence for inline backtick runs inside code', () => {
            const node: NotebookBlockNode = {
                id: '',
                type: 'code',
                language: 'javascript',
                text: 'console.log("```")',
            }

            expect(serializeNode(node)).toEqual('````javascript\nconsole.log("```")\n````')
        })

        it('round-trips code containing fence lines exactly', () => {
            const codeText = '```\ninner\n```\n````\ndeeper\n````'
            const document = makeDocument([
                { id: '', type: 'code', language: undefined, text: codeText },
                paragraph([text('after the code')]),
            ])
            const result = roundTrip(document)

            expect(result.nodes.map((node) => node.type)).toEqual(['code', 'paragraph'])
            expect(getNodeText(result.nodes[0])).toEqual(codeText)
        })
    })

    describe('underscore and asterisk emphasis', () => {
        it('parses underscore emphasis at word boundaries', () => {
            const nodes = parseMarkdownNotebook('_em_ and __strong__ but not user_id or snake_case_words').nodes

            expect(nodes).toHaveLength(1)
            const children = (nodes[0] as NotebookTextBlockNode).children
            expect(children[0]).toEqual({ type: 'text', text: 'em', marks: [{ type: 'italic' }] })
            expect(children[2]).toEqual({ type: 'text', text: 'strong', marks: [{ type: 'bold' }] })
            expect(getNodeText(nodes[0])).toEqual('em and strong but not user_id or snake_case_words')
        })

        it('does not italicize asterisks next to whitespace', () => {
            const nodes = parseMarkdownNotebook('3 * 4 * 5 stays literal').nodes

            expect(getNodeText(nodes[0])).toEqual('3 * 4 * 5 stays literal')
            expect((nodes[0] as NotebookTextBlockNode).children).toHaveLength(1)
        })

        it('round-trips bold plus italic via **_text_**', () => {
            const document = makeDocument([
                paragraph([text('before '), text('both', [{ type: 'bold' }, { type: 'italic' }]), text(' after')]),
            ])

            expect(serializeMarkdownNotebook(document)).toEqual('before **_both_** after')
            expect(stripIds(roundTrip(document))).toEqual(stripIds(document))
        })

        it('hoists boundary whitespace out of emphasis delimiters', () => {
            const document = makeDocument([paragraph([text('a'), text(' spaced ', [{ type: 'bold' }]), text('b')])])

            expect(serializeMarkdownNotebook(document)).toEqual('a **spaced** b')
            expect(getNodeText(roundTrip(document).nodes[0])).toEqual('a spaced b')
        })
    })

    describe('links', () => {
        it('round-trips hrefs containing balanced parentheses', () => {
            const href = 'https://en.wikipedia.org/wiki/Hog_(disambiguation)'
            const document = makeDocument([paragraph([text('wiki', [{ type: 'link', href }])])])
            const result = roundTrip(document)

            const children = (result.nodes[0] as NotebookTextBlockNode).children
            expect(children[0]).toEqual({ type: 'text', text: 'wiki', marks: [{ type: 'link', href }] })
        })

        it('parses external links with unescaped balanced parentheses', () => {
            const nodes = parseMarkdownNotebook('[wiki](https://en.wikipedia.org/wiki/Hog_(disambiguation)) end').nodes
            const children = (nodes[0] as NotebookTextBlockNode).children

            expect(children[0].type === 'text' && children[0].marks?.[0]).toEqual({
                type: 'link',
                href: 'https://en.wikipedia.org/wiki/Hog_(disambiguation)',
            })
            expect(getNodeText(nodes[0])).toEqual('wiki end')
        })

        it('drops disallowed link schemes but keeps the label text', () => {
            // eslint-disable-next-line no-script-url
            const nodes = parseMarkdownNotebook('[click](javascript:alert(1)) safe').nodes

            expect(getNodeText(nodes[0])).toEqual('click safe')
            expect(
                (nodes[0] as NotebookTextBlockNode).children.every(
                    (child) => child.type === 'hardBreak' || !child.marks
                )
            ).toBe(true)
        })
    })

    describe('tables', () => {
        it('does not absorb a following paragraph containing a pipe', () => {
            const markdown = '| a | b |\n| --- | --- |\n| 1 | 2 |\neither | or'
            const nodes = parseMarkdownNotebook(markdown).nodes

            expect(nodes.map((node) => node.type)).toEqual(['table', 'paragraph'])
            expect((nodes[0] as NotebookTableBlockNode).rows).toHaveLength(1)
            expect(getNodeText(nodes[1])).toEqual('either | or')
        })

        it('does not parse prose containing a pipe as a table header', () => {
            const nodes = parseMarkdownNotebook('a | b\n--- | ---').nodes

            expect(nodes.every((node) => node.type !== 'table')).toBe(true)
        })

        it('round-trips cells containing pipes and code spans', () => {
            const document = makeDocument([
                {
                    id: '',
                    type: 'table',
                    headers: [{ children: [text('a | b')] }, { children: [text('shell', [{ type: 'code' }])] }],
                    rows: [[{ children: [text('x|y')] }, { children: [text('cmd | grep', [{ type: 'code' }])] }]],
                    alignments: [],
                },
            ])
            const result = roundTrip(document)
            const table = result.nodes[0] as NotebookTableBlockNode

            expect(getNodeText(table)).toEqual(getNodeText(document.nodes[0]))
        })
    })

    describe('inline ref and mention tags', () => {
        it('parses a ref tag into a ref mark', () => {
            const nodes = parseMarkdownNotebook('Before <ref id="banana">highlighted text</ref> after').nodes
            const node = nodes[0] as NotebookTextBlockNode

            expect(node.children).toEqual([
                { type: 'text', text: 'Before ' },
                { type: 'text', text: 'highlighted text', marks: [{ type: 'ref', id: 'banana' }] },
                { type: 'text', text: ' after' },
            ])
        })

        it('parses a mention tag into a mention mark', () => {
            const nodes = parseMarkdownNotebook('Ping <mention id="5">@Marius</mention> please').nodes
            const node = nodes[0] as NotebookTextBlockNode

            expect(node.children[1]).toEqual({
                type: 'text',
                text: '@Marius',
                marks: [{ type: 'mention', id: '5' }],
            })
        })

        it('round-trips ref and mention marks', () => {
            const document = makeDocument([
                paragraph([
                    text('Hello '),
                    text('@Marius', [{ type: 'mention', id: '5' }]),
                    text(' look at '),
                    text('this number', [{ type: 'ref', id: 'banana' }]),
                ]),
            ])

            expect(serializeMarkdownNotebook(document)).toEqual(
                'Hello <mention id="5">@Marius</mention> look at <ref id="banana">this number</ref>'
            )
            expect(stripIds(roundTrip(document))).toEqual(stripIds(document))
        })

        it('keeps formatting marks inside the ref tag', () => {
            const document = makeDocument([
                paragraph([text('important', [{ type: 'bold' }, { type: 'ref', id: 'r1' }])]),
            ])

            expect(serializeMarkdownNotebook(document)).toEqual('<ref id="r1">**important**</ref>')
            expect(stripIds(roundTrip(document))).toEqual(stripIds(document))
        })

        it('parses formatting nested inside a ref tag', () => {
            const nodes = parseMarkdownNotebook('<ref id="r1">plain **bold** tail</ref>').nodes
            const node = nodes[0] as NotebookTextBlockNode

            expect(node.children).toEqual([
                { type: 'text', text: 'plain ', marks: [{ type: 'ref', id: 'r1' }] },
                { type: 'text', text: 'bold', marks: [{ type: 'bold' }, { type: 'ref', id: 'r1' }] },
                { type: 'text', text: ' tail', marks: [{ type: 'ref', id: 'r1' }] },
            ])
        })

        it.each(['<ref id="x">unclosed', '<ref>no id</ref>', '<ref id="">empty</ref>', '<refid="x">a</ref>'])(
            'treats malformed inline tag %s as literal text',
            (markdown) => {
                const nodes = parseMarkdownNotebook(markdown).nodes
                const node = nodes[0] as NotebookTextBlockNode

                expect(node.children.every((child) => child.type !== 'text' || !child.marks?.length)).toBe(true)
                expect(getNodeText(node)).toEqual(markdown)
            }
        )

        it('round-trips literal ref-looking text without creating a mark', () => {
            const document = makeDocument([paragraph([text('see <ref id="x">this</ref> tag')])])
            const result = roundTrip(document)

            expect(stripIds(result)).toEqual(stripIds(document))
        })

        it('round-trips ref marks inside list items', () => {
            const document = makeDocument([
                {
                    id: '',
                    type: 'list',
                    ordered: false,
                    items: [
                        {
                            children: [text('todo item', [{ type: 'ref', id: 'r2' }])],
                            depth: 0,
                            ordered: false,
                            start: undefined,
                        },
                    ],
                },
            ])

            expect(stripIds(roundTrip(document))).toEqual(stripIds(document))
        })
    })

    describe('discussion comment tags', () => {
        it('round-trips a discussion comment as a JSX tag, not an html comment', () => {
            const markdown = '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"Looks off"}]} />'
            const nodes = parseMarkdownNotebook(markdown).nodes

            expect(nodes[0]).toMatchObject({
                type: 'component',
                tagName: 'Comment',
                props: {
                    ref: 'banana',
                    replies: [{ id: 'r1', author: 'Ann', text: 'Looks off' }],
                },
            })
            expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
        })

        it('keeps the authorial note flavor serializing as an html comment', () => {
            const document = makeDocument([
                { id: '', type: 'component', tagName: 'Comment', props: { text: 'just a note' } },
            ])

            expect(serializeMarkdownNotebook(document)).toEqual('<!-- just a note -->')
        })
    })

    describe('list indentation', () => {
        it('clamps externally indented nesting to one level per step', () => {
            const nodes = parseMarkdownNotebook('- parent\n    - child\n        - grandchild').nodes
            const list = nodes[0] as NotebookListBlockNode

            expect(list.items.map((item) => item.depth)).toEqual([0, 1, 2])
        })

        it('keeps two-space nesting unchanged', () => {
            const nodes = parseMarkdownNotebook('- parent\n  - child\n- sibling').nodes
            const list = nodes[0] as NotebookListBlockNode

            expect(list.items.map((item) => item.depth)).toEqual([0, 1, 0])
        })
    })

    describe('task lists', () => {
        it('parses checked and unchecked task markers on bullet items', () => {
            const nodes = parseMarkdownNotebook('- [ ] open\n- [x] done\n- [X] also done\n- plain').nodes
            const list = nodes[0] as NotebookListBlockNode

            expect(list.items.map((item) => item.checked)).toEqual([false, true, true, undefined])
            expect(list.items.map((item) => getInlineText(item.children))).toEqual([
                'open',
                'done',
                'also done',
                'plain',
            ])
        })

        it('serializes task state back to GFM markers and reaches a fixpoint', () => {
            const markdown = '- [ ] open\n- [x] done\n  - [ ] nested open\n- plain'

            expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
        })

        it('parses an empty task item without a trailing space', () => {
            const list = parseMarkdownNotebook('- [ ]').nodes[0] as NotebookListBlockNode

            expect(list.items[0].checked).toEqual(false)
            expect(list.items[0].children).toEqual([])
        })

        it('keeps a task marker on an ordered item as literal text', () => {
            const list = parseMarkdownNotebook('1. [x] not a task').nodes[0] as NotebookListBlockNode

            expect(list.items[0].checked).toBeUndefined()
            expect(getNodeText(list)).toEqual('[x] not a task')
        })

        it('does not parse a marker without following whitespace as a task', () => {
            const list = parseMarkdownNotebook('- [x](https://posthog.com/docs) linked')
                .nodes[0] as NotebookListBlockNode

            expect(list.items[0].checked).toBeUndefined()
        })

        it('round-trips literal task-marker text in a bullet item without creating a task', () => {
            const document = makeDocument([
                {
                    id: '',
                    type: 'list',
                    ordered: false,
                    items: [{ children: [text('[x] literal marker')], depth: 0, ordered: false, start: undefined }],
                },
            ])
            const result = roundTrip(document)
            const list = result.nodes[0] as NotebookListBlockNode

            expect(list.items[0].checked).toBeUndefined()
            expect(getNodeText(list)).toEqual('[x] literal marker')
            expect(stripIds(roundTrip(result))).toEqual(stripIds(result))
        })

        it('round-trips task items inside a blockquoted list', () => {
            const markdown = '> - [x] quoted done\n> - [ ] quoted open'

            expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
        })
    })
})
