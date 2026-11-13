import { quillExportMap, rewriteQuillImports } from './quillImports.mjs'

const INDEX = `/* empty css */
import { Button as e, buttonVariants as t } from "./button2.js";
import { Drawer as n } from "./drawer2.js";
import { DirectionProvider as r } from "@base-ui/react/direction-provider";
export { e as Button, r as DirectionProvider, n as Drawer, t as buttonVariants };
export { cn } from "./lib/utils.js";
export { useDirection } from "@base-ui/react/direction-provider";
`

describe('quillImports', () => {
    const primitives = quillExportMap(INDEX, '/dist')
    const maps = new Map([
        ['@posthog/quill', primitives],
        ['lib/ui/quill', primitives],
    ])

    it('maps each export of a built index to the quill file that defines it', () => {
        expect(Object.fromEntries(primitives)).toEqual({
            Button: { file: '/dist/button2.js', imported: 'Button' },
            buttonVariants: { file: '/dist/button2.js', imported: 'buttonVariants' },
            Drawer: { file: '/dist/drawer2.js', imported: 'Drawer' },
            cn: { file: '/dist/lib/utils.js', imported: 'cn' },
        })
    })

    it.each([
        {
            name: 'one statement per defining file',
            source: `import { Button, Drawer, buttonVariants } from '@posthog/quill'\n`,
            expected: `import { Button, buttonVariants } from "/dist/button2.js"; import { Drawer } from "/dist/drawer2.js";\n`,
        },
        {
            name: 'the app re-export file and a local alias',
            source: `    import { Button as QuillButton } from 'lib/ui/quill'\n`,
            expected: `    import { Button as QuillButton } from "/dist/button2.js";\n`,
        },
        {
            name: 'unknown names and inline types stay on the index',
            source: `import { Button, type ButtonProps, Unknown } from '@posthog/quill'\n`,
            expected: `import { Button } from "/dist/button2.js"; import { type ButtonProps, Unknown } from '@posthog/quill';\n`,
        },
        {
            // A changed line count would shift every later line in the file's source map.
            name: 'a statement over several lines keeps its line count',
            source: `import {\n    Button,\n    Drawer,\n} from '@posthog/quill'\nconst after = 1\n`,
            expected: `import { Button } from "/dist/button2.js"; import { Drawer } from "/dist/drawer2.js";\n\n\n\nconst after = 1\n`,
        },
        {
            name: 'only the imports before the first template literal',
            source: `import { Button } from '@posthog/quill'\nconst text = \`\nimport { Drawer } from '@posthog/quill'\n\`\n`,
            expected: `import { Button } from "/dist/button2.js";\nconst text = \`\nimport { Drawer } from '@posthog/quill'\n\`\n`,
        },
    ])('rewrites $name', ({ source, expected }) => {
        expect(rewriteQuillImports(source, maps)).toEqual(expected)
    })

    it.each([
        ['a type-only import', `import type { ButtonProps } from '@posthog/quill'\n`],
        ['another package', `import { Button } from '@posthog/lemon-ui'\n`],
        ['a comment inside the import list', `import {\n    // keep\n    Button,\n} from '@posthog/quill'\n`],
        ['an import in a string', `const text = "import { Button } from '@posthog/quill'"\n`],
    ])('leaves %s alone', (_name, source) => {
        expect(rewriteQuillImports(source, maps)).toBeNull()
    })
})

describe('quillExportMap', () => {
    it.each([
        ['a multi-line statement', `export {\n  a as Button,\n};\n`],
        ['a star export', `export * from "./button2.js";\n`],
        ['a name that nothing defines', `export { e as Button };\n`],
    ])('throws on %s instead of leaving names on the index', (_name, index) => {
        expect(() => quillExportMap(index, '/dist')).toThrow(/quill-imports/)
    })
})
