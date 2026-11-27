import fs from 'fs'
import path from 'path'
import ts from 'typescript'

const RULE_IDS = ['F1', 'F2', 'F3', 'F4'] as const
type Rule = (typeof RULE_IDS)[number]

interface ImportRef {
    specifier: string
    typeOnly: boolean
    names: string[]
}

const REDESIGN = __dirname
const PRODUCT_FRONTEND = path.resolve(REDESIGN, '..')
const REPO_ROOT = path.resolve(PRODUCT_FRONTEND, '../../..')
const PRODUCT_PACKAGE = '@posthog/products-ai-observability'
const KEA_ROUTER_PURE_HELPERS = ['combineUrl', 'encodeParams', 'decodeParams']
const VERSION_WORD = /^(legacy|redesign|v\d+)$/

const RULES: Record<Rule, string> = {
    F1: 'A component imports no kea (products/ai_observability/AGENTS.md, "Where layered code goes").',
    F2: 'A plain module imports no kea or React (products/ai_observability/AGENTS.md, "Where layered code goes").',
    F3: 'Only a *Host.tsx imports older AI observability frontend code (products/ai_observability/AGENTS.md, "Where layered code goes").',
    F4: 'No version words in file names or data-attrs (.agents/skills/working-on-ai-observability/references/frontend.md).',
}

const KNOWN_BREAKS: Record<Rule, string[]> = {
    F1: [],
    F2: [],
    F3: ['trace/components/AttachmentImage.tsx', 'trace/traceBackLink.ts', 'trace/traceReviewLogic.ts'],
    F4: [],
}

function isTestSupport(relativePath: string): boolean {
    const name = path.basename(relativePath)
    return (
        /\.(test|spec)\.tsx?$/.test(name) ||
        name.endsWith('.stories.tsx') ||
        relativePath.split(path.sep).some((part) => part === '__mocks__' || part === 'test')
    )
}

function sourceFiles(directory: string = REDESIGN): string[] {
    return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const fullPath = path.join(directory, entry.name)
        if (entry.isDirectory()) {
            return sourceFiles(fullPath)
        }
        return /\.tsx?$/.test(entry.name) && !isTestSupport(path.relative(REDESIGN, fullPath)) ? [fullPath] : []
    })
}

function parse(filePath: string, source: string = fs.readFileSync(filePath, 'utf8')): ts.SourceFile {
    const kind = filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    return ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, kind)
}

function importRef(declaration: ts.ImportDeclaration): ImportRef | null {
    if (!ts.isStringLiteral(declaration.moduleSpecifier)) {
        return null
    }
    const clause = declaration.importClause
    const named = clause?.namedBindings && ts.isNamedImports(clause.namedBindings) ? clause.namedBindings.elements : []
    const names = [
        ...(clause?.name ? ['default'] : []),
        ...(clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings) ? ['*'] : []),
        ...named.map((element) => (element.propertyName ?? element.name).text),
    ]
    const everyNamedIsType = !clause?.name && named.length > 0 && named.every((element) => element.isTypeOnly)
    return {
        specifier: declaration.moduleSpecifier.text,
        typeOnly: Boolean(clause?.isTypeOnly) || everyNamedIsType,
        names,
    }
}

function collectImports(sourceFile: ts.SourceFile): ImportRef[] {
    const refs: ImportRef[] = []
    const visit = (node: ts.Node): void => {
        const ref = ts.isImportDeclaration(node) ? importRef(node) : null
        if (ref) {
            refs.push(ref)
        } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
            refs.push({ specifier: node.moduleSpecifier.text, typeOnly: node.isTypeOnly, names: ['*'] })
        } else if (
            ts.isCallExpression(node) &&
            node.expression.kind === ts.SyntaxKind.ImportKeyword &&
            node.arguments[0] &&
            ts.isStringLiteralLike(node.arguments[0])
        ) {
            refs.push({ specifier: node.arguments[0].text, typeOnly: false, names: ['*'] })
        }
        ts.forEachChild(node, visit)
    }
    visit(sourceFile)
    return refs
}

function isOldFrontend(fromFile: string, specifier: string): boolean {
    let resolved: string
    if (specifier.startsWith('.')) {
        resolved = path.resolve(path.dirname(fromFile), specifier)
    } else if (specifier.startsWith('products/')) {
        resolved = path.resolve(REPO_ROOT, specifier)
    } else if (specifier.startsWith(`${PRODUCT_PACKAGE}/`)) {
        resolved = path.resolve(PRODUCT_FRONTEND, '..', specifier.slice(PRODUCT_PACKAGE.length + 1))
    } else {
        return false
    }
    const relative = path.relative(PRODUCT_FRONTEND, resolved)
    if (relative.startsWith('..') || path.isAbsolute(relative)) {
        return false
    }
    const top = relative.split(path.sep)[0]
    return top !== 'redesign' && top !== 'generated'
}

function importsKea(ref: ImportRef): boolean {
    if (ref.typeOnly || !(ref.specifier === 'kea' || ref.specifier.startsWith('kea-'))) {
        return false
    }
    return !(
        ref.specifier === 'kea-router' &&
        ref.names.length > 0 &&
        ref.names.every((name) => KEA_ROUTER_PURE_HELPERS.includes(name))
    )
}

function hasVersionWord(text: string): boolean {
    return text
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .split(/[\s\-_./]+/)
        .some((word) => VERSION_WORD.test(word.toLowerCase()))
}

function dataAttrs(sourceFile: ts.SourceFile): string[] {
    const values: string[] = []
    const visit = (node: ts.Node): void => {
        if (ts.isJsxAttribute(node) && node.name.getText(sourceFile) === 'data-attr' && node.initializer) {
            const value = ts.isJsxExpression(node.initializer) ? node.initializer.expression : node.initializer
            if (value && ts.isStringLiteralLike(value)) {
                values.push(value.text)
            } else if (value && ts.isTemplateExpression(value)) {
                values.push([value.head.text, ...value.templateSpans.map((span) => span.literal.text)].join('-'))
            }
        }
        ts.forEachChild(node, visit)
    }
    visit(sourceFile)
    return values
}

function breaksOf(filePath: string): Rule[] {
    const relative = path.relative(REDESIGN, filePath)
    const sourceFile = parse(filePath)
    const imports = collectImports(sourceFile)
    const inComponents = relative.split(path.sep).includes('components')
    const isPlainModule = filePath.endsWith('.ts') && !inComponents && !filePath.endsWith('Logic.ts')
    const breaks: Rule[] = []
    if (inComponents && imports.some(importsKea)) {
        breaks.push('F1')
    }
    if (isPlainModule && imports.some((ref) => importsKea(ref) || (!ref.typeOnly && ref.specifier === 'react'))) {
        breaks.push('F2')
    }
    if (!filePath.endsWith('Host.tsx') && imports.some((ref) => isOldFrontend(filePath, ref.specifier))) {
        breaks.push('F3')
    }
    if (hasVersionWord(relative.replace(/\.tsx?$/, '')) || dataAttrs(sourceFile).some(hasVersionWord)) {
        breaks.push('F4')
    }
    return breaks
}

function currentBreaks(): Record<Rule, string[]> {
    const found: Record<Rule, string[]> = { F1: [], F2: [], F3: [], F4: [] }
    for (const filePath of sourceFiles()) {
        for (const rule of breaksOf(filePath)) {
            found[rule].push(path.relative(REDESIGN, filePath))
        }
    }
    return found
}

describe('redesign layer boundaries', () => {
    const found = currentBreaks()

    it.each(RULE_IDS)('%s holds outside the known breaks', (rule) => {
        const newBreaks = found[rule].filter((file) => !KNOWN_BREAKS[rule].includes(file))
        expect({ rule: RULES[rule], newBreaks }).toEqual({ rule: RULES[rule], newBreaks: [] })
    })

    it('lists only known breaks that still break their rule', () => {
        const stale = RULE_IDS.flatMap((rule) =>
            KNOWN_BREAKS[rule]
                .filter((file) => !found[rule].includes(file))
                .map((file) => `remove ${file} from KNOWN_BREAKS.${rule}`)
        )
        expect(stale).toEqual([])
    })

    it('treats a type-only kea import as no import', () => {
        const [ref] = collectImports(parse('x.ts', "import type { BuiltLogic } from 'kea'"))
        expect(importsKea(ref)).toBe(false)
    })

    it('treats kea-router URL helpers as pure and the router as kea', () => {
        const [helpers, routerImport] = collectImports(
            parse(
                'x.ts',
                "import { combineUrl } from 'kea-router'\nimport { combineUrl as c, router } from 'kea-router'"
            )
        )
        expect([importsKea(helpers), importsKea(routerImport)]).toEqual([false, true])
    })

    it.each([
        ['trace/components/AttachmentImage.tsx', '../../../components/AIImage', true],
        ['trace/components/AttachmentImage.tsx', 'products/ai_observability/frontend/components/AIImage', true],
        ['trace/traceLogic.ts', '@posthog/products-ai-observability/frontend/components/AIImage', true],
        ['trace/traceLogic.ts', '@posthog/products-ai-observability/frontend/redesign/shared/readOrFailure', false],
        ['trace/traceLogic.ts', '../shared/readOrFailure', false],
        ['trace/traceLogic.ts', '../../generated/api', false],
        ['trace/traceLogic.ts', 'products/persons/frontend/PersonDisplay', false],
        ['trace/traceLogic.ts', '~/lib/utils', false],
    ])('from %s, %s is old code: %s', (fromFile, specifier, expected) => {
        expect(isOldFrontend(path.join(REDESIGN, fromFile), specifier)).toBe(expected)
    })

    it.each([
        ['trace/TraceViewV2', true],
        ['legacy-trace-link', true],
        ['trace/redesignBanner', true],
        ['new-prompt-button', false],
        ['trace/TraceView', false],
        ['views/overview', false],
    ])('%s has a version word: %s', (text, expected) => {
        expect(hasVersionWord(text)).toBe(expected)
    })

    it('reads data-attrs written as template literals', () => {
        const sourceFile = parse('x.tsx', 'const a = <div data-attr={`trace-v2-${id}`} />')
        expect(dataAttrs(sourceFile).some(hasVersionWord)).toBe(true)
    })

    it.each([
        ['trace/components/testHogPanel.tsx', false],
        ['trace/TraceView.test.tsx', true],
        ['trace/TraceView.stories.tsx', true],
        ['trace/__mocks__/trace.ts', true],
    ])('%s is test support: %s', (relativePath, expected) => {
        expect(isTestSupport(relativePath)).toBe(expected)
    })
})
