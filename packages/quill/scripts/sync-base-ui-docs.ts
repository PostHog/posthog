/**
 * Copies Base UI's component documentation onto the quill wrappers that render it.
 *
 * Quill primitives already forward Base UI's prop *types*, so hovering an individual prop
 * shows Base UI's JSDoc for it. Hovering the component itself showed nothing, because the
 * wrapper carried no doc comment of its own. This script closes that gap: for every wrapper
 * that spreads its rest props onto a Base UI element, it reads the doc comment off that Base
 * UI component (via the TypeScript checker, so it always matches the installed version) and
 * writes it above the wrapper.
 *
 * Generated content sits at the top of the block and ends at the `@baseui` tag. Anything
 * after that tag is hand-written and is preserved verbatim across runs, so re-running after
 * a Base UI upgrade refreshes the upstream prose without touching quill's own notes.
 *
 * Usage: pnpm --filter @posthog/quill-workspace sync:base-ui-docs [--check]
 */
import { writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const HERE = dirname(fileURLToPath(import.meta.url))
const PACKAGES = ['primitives', 'components', 'blocks'].map((name) => join(HERE, '..', 'packages', name))
const BASE_UI_MODULE = /^@base-ui\/react(\/|$)/
const TAG = 'baseui'

interface Wrapper {
    /** Declaration the doc block is attached to (the `function`/`const` statement). */
    node: ts.Node
    /** Qualified Base UI name, e.g. `Accordion.Root`. */
    baseUiName: string
    /** Base UI's own doc comment for that component. */
    doc: string
}

/** The rest-element name of a destructured first parameter, e.g. `props` in `({ className, ...props })`. */
function restParamName(params: ts.NodeArray<ts.ParameterDeclaration>): string | undefined {
    const binding = params[0]?.name
    if (!binding || !ts.isObjectBindingPattern(binding)) {
        return undefined
    }
    const rest = binding.elements.find((element) => element.dotDotDotToken)
    return rest && ts.isIdentifier(rest.name) ? rest.name.text : undefined
}

/** The JSX element that receives `{...rest}` — the one the wrapper actually forwards props to. */
function findForwardTarget(body: ts.Node, rest: string): ts.JsxOpeningLikeElement | undefined {
    let found: ts.JsxOpeningLikeElement | undefined
    const visit = (node: ts.Node): void => {
        if (found) {
            return
        }
        if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
            const spreads = node.attributes.properties.some(
                (attribute) =>
                    ts.isJsxSpreadAttribute(attribute) &&
                    ts.isIdentifier(attribute.expression) &&
                    attribute.expression.text === rest
            )
            if (spreads) {
                found = node
                return
            }
        }
        ts.forEachChild(node, visit)
    }
    visit(body)
    return found
}

/** Walks an import alias back to the module it came from. */
function declaringModule(symbol: ts.Symbol): string | undefined {
    const declaration = symbol.declarations?.[0]
    const importClause = declaration && ts.isImportSpecifier(declaration) ? declaration : undefined
    if (!importClause) {
        return undefined
    }
    const specifier = importClause.parent.parent.parent.moduleSpecifier
    return ts.isStringLiteral(specifier) ? specifier.text : undefined
}

/** Resolves `<AccordionPrimitive.Root>` to `{ name: 'Accordion.Root', doc }` when it comes from Base UI. */
function resolveBaseUi(
    checker: ts.TypeChecker,
    tag: ts.JsxTagNameExpression
): { name: string; doc: string } | undefined {
    const root = ts.isPropertyAccessExpression(tag) ? tag.expression : tag
    if (!ts.isIdentifier(root)) {
        return undefined
    }
    const rootSymbol = checker.getSymbolAtLocation(root)
    if (!rootSymbol) {
        return undefined
    }
    const module = declaringModule(rootSymbol)
    if (!module || !BASE_UI_MODULE.test(module)) {
        return undefined
    }
    // Prefer the imported name over the local alias, so the tag reads `Accordion.Root`
    // rather than quill's `AccordionPrimitive.Root`.
    const declaration = rootSymbol.declarations?.[0] as ts.ImportSpecifier
    const upstreamRoot = (declaration.propertyName ?? declaration.name).text
    const part = ts.isPropertyAccessExpression(tag) ? `.${tag.name.text}` : ''

    const symbol = checker.getSymbolAtLocation(tag)
    if (!symbol) {
        return undefined
    }
    const target = symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol
    const doc = ts.displayPartsToString(target.getDocumentationComment(checker)).trim()
    if (!doc) {
        return undefined
    }
    return { name: `${upstreamRoot}${part}`, doc }
}

/** Existing doc block on a declaration, if it has one. */
function existingDoc(node: ts.Node, text: string): ts.CommentRange | undefined {
    const ranges = ts.getLeadingCommentRanges(text, node.pos) ?? []
    const block = ranges.filter((range) => text.slice(range.pos, range.pos + 3) === '/**').pop()
    return block
}

/** Hand-written prose lives after the `@baseui` tag; a block without the tag is hand-written whole. */
function handWrittenTail(block: string): string {
    const inner = block
        .replace(/^\/\*\*/, '')
        .replace(/\*\/$/, '')
        .split('\n')
        .map((line) => line.replace(/^\s*\* ?/, ''))
    const tagIndex = inner.findIndex((line) => line.trimStart().startsWith(`@${TAG} `))
    const tail = tagIndex === -1 ? inner : inner.slice(tagIndex + 1)
    return tail.join('\n').trim()
}

function renderDoc(wrapper: Wrapper, tail: string, indent: string): string {
    const lines = [...wrapper.doc.split('\n'), '', `@${TAG} ${wrapper.baseUiName}`]
    if (tail) {
        lines.push('', ...tail.split('\n'))
    }
    const body = lines.map((line) => `${indent} *${line ? ` ${line}` : ''}`).join('\n')
    return `${indent}/**\n${body}\n${indent} */`
}

function collectWrappers(source: ts.SourceFile, checker: ts.TypeChecker): Wrapper[] {
    const wrappers: Wrapper[] = []
    const consider = (
        statement: ts.Node,
        fn: ts.FunctionDeclaration | ts.FunctionExpression | ts.ArrowFunction
    ): void => {
        const rest = restParamName(fn.parameters)
        if (!rest || !fn.body) {
            return
        }
        const target = findForwardTarget(fn.body, rest)
        if (!target) {
            return
        }
        const resolved = resolveBaseUi(checker, target.tagName)
        if (resolved) {
            wrappers.push({ node: statement, baseUiName: resolved.name, doc: resolved.doc })
        }
    }

    for (const statement of source.statements) {
        if (ts.isFunctionDeclaration(statement)) {
            consider(statement, statement)
            continue
        }
        if (!ts.isVariableStatement(statement) || statement.declarationList.declarations.length !== 1) {
            continue
        }
        const initializer = statement.declarationList.declarations[0].initializer
        if (!initializer) {
            continue
        }
        // `const X = React.forwardRef(function X(props, ref) { … })` and plain arrow/function forms.
        const inner = ts.isCallExpression(initializer) ? initializer.arguments[0] : initializer
        if (inner && (ts.isArrowFunction(inner) || ts.isFunctionExpression(inner))) {
            consider(statement, inner)
        }
    }
    return wrappers
}

function main(): void {
    const check = process.argv.includes('--check')
    let changed = 0

    for (const packageDir of PACKAGES) {
        const configPath = ts.findConfigFile(packageDir, ts.sys.fileExists, 'tsconfig.json')
        if (!configPath) {
            continue
        }
        const config = ts.readConfigFile(configPath, ts.sys.readFile)
        const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, dirname(configPath))
        const program = ts.createProgram(parsed.fileNames, parsed.options)
        const checker = program.getTypeChecker()

        for (const source of program.getSourceFiles()) {
            if (source.isDeclarationFile || !source.fileName.startsWith(resolve(packageDir))) {
                continue
            }
            if (source.fileName.includes('.stories.')) {
                continue
            }
            const wrappers = collectWrappers(source, checker)
            if (wrappers.length === 0) {
                continue
            }

            const original = source.getFullText()
            let text = original
            // Rewrite bottom-up so earlier edits don't shift later offsets.
            for (const wrapper of [...wrappers].reverse()) {
                const start = wrapper.node.getStart(source)
                const line = text.lastIndexOf('\n', start - 1) + 1
                const indent = text.slice(line, start)
                if (indent.trim() !== '') {
                    continue
                }
                const block = existingDoc(wrapper.node, text)
                const tail = block ? handWrittenTail(text.slice(block.pos, block.end)) : ''
                const rendered = renderDoc(wrapper, tail, indent)
                text = block
                    ? `${text.slice(0, block.pos)}${rendered.trimStart()}${text.slice(block.end)}`
                    : `${text.slice(0, line)}${rendered}\n${text.slice(line)}`
            }

            if (text === original) {
                continue
            }
            changed += 1
            if (!check) {
                writeFileSync(source.fileName, text)
            }
            process.stdout.write(`${check ? 'stale' : 'updated'}: ${source.fileName}\n`)
        }
    }

    if (check && changed > 0) {
        process.stderr.write(`\n${changed} file(s) out of sync — run pnpm sync:base-ui-docs\n`)
        process.exit(1)
    }
    process.stdout.write(`${changed} file(s) ${check ? 'stale' : 'updated'}\n`)
}

main()
