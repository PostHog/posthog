import { blockDefinition, freshBlockProps } from './blockDefinitions'
import { blockRanges, DropPlace, moveRange, placeableTarget, setJsxAttributes } from './sourceEdits'

const FILE = 'src/canvas.tsx'

function edit(source: string, values: Record<string, string | number | boolean | string[] | undefined>): string {
    const start = source.indexOf('<Panel')
    const end = source.lastIndexOf('>') + 1
    return setJsxAttributes({ [FILE]: source }, { file: FILE, start, end }, values)[FILE] ?? ''
}

const NESTED = `<main>
  <section>
    <p>A</p>
    <p>B</p>
  </section>
</main>`

function nestedRange(snippet: string): { file: string; start: number; end: number } {
    const start = NESTED.indexOf(snippet)
    return { file: FILE, start, end: start + snippet.length }
}

const TWO_ROOTS = `function Game() {
  return (
    <div>
      <h2>Title</h2>
    </div>
  )
}

export default function Canvas() {
  return (
    <main>
      <Card title="A" />
    </main>
  )
}
`
const ROOT = {
    file: FILE,
    start: TWO_ROOTS.indexOf('<main>'),
    end: TWO_ROOTS.indexOf('</main>') + '</main>'.length,
}
const TITLE = {
    file: FILE,
    start: TWO_ROOTS.indexOf('<h2>'),
    end: TWO_ROOTS.indexOf('</h2>') + '</h2>'.length,
}
const CARD = {
    file: FILE,
    start: TWO_ROOTS.indexOf('<Card'),
    end: TWO_ROOTS.indexOf('/>') + 2,
}

describe('sourceEdits', () => {
    it.each([
        {
            name: 'replaces a string prop and keeps expression props',
            source: '<Panel title="Old" range={dateRange} onPick={(v) => set({ v })} />',
            values: { title: 'New' },
            expected: '<Panel title="New" range={dateRange} onPick={(v) => set({ v })} />',
        },
        {
            name: 'adds a prop to a self-closing tag',
            source: '<Panel {...shared} />',
            values: { limit: 5 },
            expected: '<Panel {...shared} limit={5} />',
        },
        {
            name: 'removes a prop',
            source: '<Panel title="A" breakdown="$browser" />',
            values: { breakdown: undefined },
            expected: '<Panel title="A" />',
        },
        {
            name: 'edits only the opening tag of an element with children',
            source: '<Panel title="A">\n  <Child title="B" />\n</Panel>',
            values: { title: 'C', steps: ['a', 'b'] },
            expected: '<Panel title="C" steps={["a","b"]}>\n  <Child title="B" />\n</Panel>',
        },
        {
            name: 'keeps a string with quotes valid',
            source: '<Panel title="A" />',
            values: { title: 'Say "hi"' },
            expected: '<Panel title={"Say \\"hi\\""} />',
        },
    ])('setJsxAttributes $name', ({ source, values, expected }) => {
        expect(edit(source, values)).toBe(expected)
    })

    it('moveRange moves a child out to just after its parent', () => {
        const section = NESTED.slice(NESTED.indexOf('<section>'), NESTED.indexOf('</section>') + '</section>'.length)
        const moved = moveRange({ [FILE]: NESTED }, nestedRange('<p>B</p>'), {
            ...nestedRange(section),
            place: 'after',
        })
        expect(moved[FILE]?.replace(/\n\s*\n/g, '\n')).toBe(`<main>
  <section>
    <p>A</p>
  </section>
  <p>B</p>
</main>`)
    })

    it.each<[string, { start: number; end: number }, DropPlace, boolean]>([
        ['inside the root', ROOT, 'inside', true],
        ['after the root', ROOT, 'after', false],
        ['before the root', ROOT, 'before', false],
        ['after a child of the root', CARD, 'after', true],
        ['after an element of a component defined outside the root', TITLE, 'after', true],
        ['at offsets that no longer point at JSX', { start: 0, end: 20 }, 'after', false],
    ])('placeableTarget %s', (_name, range, place, expected) => {
        expect(
            placeableTarget({ files: { [FILE]: TWO_ROOTS }, rootSource: ROOT }, { file: FILE, ...range, place })
        ).toBe(expected)
    })
})

test('finds data blocks and used presets after comparison attributes', () => {
    const definition = blockDefinition('Funnel')!
    const title = String(definition.presets![0].title)
    const source = `<Funnel sql={"SELECT 1 WHERE 2 >= 1"} title="${title}" />`
    const files = { [FILE]: source }
    expect(blockRanges(files, FILE, 'Data')).toEqual([{ file: FILE, start: 0, end: source.length }])
    if (definition.presets!.length > 1) {
        expect(freshBlockProps(definition, files)).toEqual(definition.presets![1])
    }
})
