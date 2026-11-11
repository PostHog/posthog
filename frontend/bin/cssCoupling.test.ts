import { classNamesUsedIn, findCouplings, rootClassesOf } from './cssCoupling.mjs'

describe('cssCoupling.mjs', () => {
    it.each([
        [
            'a nested BEM block',
            '.PropertyFilters {\n  display: flex;\n  .PropertyFilters__content { gap: 1px; }\n}',
            ['PropertyFilters'],
        ],
        ['each selector in a list', '.Foo, .Bar:hover { color: red; }', ['Bar', 'Foo']],
        ['no element or modifier only selectors', '.Foo__row { a: b; }\n.Foo--active { a: b; }', []],
        ['no lower-case classes that shadow utilities', '.flex { display: flex; }', []],
        ['no global or attribute-scoped selectors', "body { a: b; }\n[theme='dark'] .Foo { a: b; }", []],
        ['no at-rules', '@media (min-width: 1px) { .Foo { a: b; } }\n@include thing;', []],
        ['no nested classes', '.Foo { .Bar { a: b; } }', ['Foo']],
        [
            'past comments and interpolation',
            '// .Old { }\n/* .Older { } */\n.Foo-#{$x} { a: b; }\n.Bar { background: url(//x/y.png); }',
            ['Bar'],
        ],
    ])('rootClassesOf finds %s', (_, scss, expected) => {
        expect(rootClassesOf(scss)).toEqual(expected)
    })

    it.each([
        ['a plain attribute', '<div className="PropertyFilters flex-wrap" />', ['PropertyFilters', 'flex-wrap']],
        ['a clsx call', "<div className={clsx('Foo', active && 'Foo--active')} />", ['Foo', 'Foo--active']],
        ['a *ClassName prop', '<Popover overlayClassName="Bar" />', ['Bar']],
        ['template literal text, not a word cut by a hole', '<div className={`Foo ${size} Baz${x}`} />', ['Foo']],
        ['no strings outside className', "<div title='Foo' />", []],
        [
            'a line comment with an apostrophe before the class',
            "<div className={\n  // don't remove\n  'Foo'\n} />",
            ['Foo'],
        ],
        [
            'a block comment with an apostrophe before the class',
            "<div className={/* don't remove */ 'Foo'} />",
            ['Foo'],
        ],
    ])('classNamesUsedIn reads %s', (_, tsx, expected) => {
        expect([...classNamesUsedIn(tsx)].sort()).toEqual(expected.sort())
    })

    const sources: Record<string, string> = {
        'PropertyFilters.scss': '.PropertyFilters { display: flex; }',
        'PropertyFilters.tsx': '<div className="PropertyFilters" />',
        'PropertyFiltersDisplay.tsx': '<div className="PropertyFilters flex-wrap" />',
        'Middle.ts': '',
    }
    it.each([
        ['no import route to the stylesheet', { 'PropertyFiltersDisplay.tsx': [] }, ['PropertyFiltersDisplay.tsx']],
        ['a direct import', { 'PropertyFiltersDisplay.tsx': ['PropertyFilters.scss'] }, []],
        [
            'a transitive import',
            { 'PropertyFiltersDisplay.tsx': ['Middle.ts'], 'Middle.ts': ['PropertyFilters.tsx'] },
            [],
        ],
    ])('findCouplings flags PropertyFiltersDisplay with %s', (_, extraImports, expected) => {
        const imports: Record<string, string[]> = { 'PropertyFilters.tsx': ['PropertyFilters.scss'], ...extraImports }
        const files = Object.fromEntries(
            Object.keys(sources).map((file) => [file, { bytes: 0, staticImports: imports[file] ?? [] }])
        )
        expect(findCouplings(files, (file: string) => sources[file]).map((c: { file: string }) => c.file)).toEqual(
            expected
        )
    })

    it('findCouplings still flags a stylesheet with no remaining importer', () => {
        // Removing the sole import drops the stylesheet from the esbuild graph entirely, so it is not
        // a key of `files`. An explicit stylesheetFiles list is the only way to still index its classes.
        const files = {
            'PropertyFiltersDisplay.tsx': { bytes: 0, staticImports: [] },
        }
        const stylesheetFiles = ['PropertyFilters.scss']
        expect(
            findCouplings(files, (file: string) => sources[file], stylesheetFiles).map((c: { file: string }) => c.file)
        ).toEqual(['PropertyFiltersDisplay.tsx'])
    })
})
