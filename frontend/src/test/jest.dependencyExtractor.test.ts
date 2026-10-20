import dependencyExtractor from '../../jest.dependencyExtractor'

const namedModules = (code: string): Set<string> =>
    new Set([...code.matchAll(/(?:require\(|from\s+)['"]([^'"]+)['"]/g)].map((match) => match[1]))

describe('jest.dependencyExtractor', () => {
    it.each([
        [
            'drops an import used only as a type',
            'shape.ts',
            `import { Shape } from './shape'\nexport const area = (shape: Shape): number => shape.width`,
            [],
        ],
        [
            'keeps an import used as a value',
            'run.ts',
            `import { helper } from './helper'\nexport const run = (): void => helper()`,
            ['./helper'],
        ],
        [
            'keeps an import used only in JSX',
            'Page.tsx',
            `import { Button } from './Button'\nexport const Page = (): JSX.Element => <Button />`,
            ['./Button'],
        ],
        [
            'keeps every import of a file the transformer cannot parse',
            'broken.ts',
            `import { Shape } from './shape'\nconst = `,
            ['./shape'],
        ],
    ])('%s', (_name, filePath, code, expected) => {
        expect([...dependencyExtractor.extract(code, filePath, namedModules)]).toEqual(expected)
    })
})
