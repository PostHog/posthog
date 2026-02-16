#!/usr/bin/env tsx
/**
 * Compiles Hog source code in warehouse source templates to bytecode.
 *
 * For each *.template.ts file in this directory:
 *   1. Parses the TypeScript AST to extract the `code` string
 *   2. Compiles it to bytecode via `./bin/hoge`
 *   3. Writes the updated `bytecode` array back into the file
 *
 * Usage:
 *   npx tsx src/cdp/templates/_sources/warehouse_source/compile-bytecode.ts
 */
import { execSync } from 'child_process'
import { mkdtempSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join, resolve } from 'path'
import ts from 'typescript'

import { parseJSON } from '~/utils/json-parse'

const TEMPLATES_DIR = __dirname
const ROOT_DIR = resolve(__dirname, '..', '..', '..', '..', '..', '..')
const LINE_WIDTH = 100
const INDENT = '        '

export function compileHogCode(code: string): any[] {
    const tempDir = mkdtempSync(join(tmpdir(), 'hog-'))
    const inputFile = join(tempDir, 'source.hog')
    const outputFile = join(tempDir, 'source.hoge')

    writeFileSync(inputFile, code)

    try {
        execSync(`cd ${ROOT_DIR} && ./bin/hoge ${inputFile} ${outputFile}`, {
            env: { ...process.env, TEST: 'true' },
            stdio: 'pipe',
        })
    } catch (error: any) {
        console.error(`Failed to compile hog code:\n${code}`)
        console.error(error.stderr?.toString())
        throw error
    }

    const bytecode = parseJSON(readFileSync(outputFile, 'utf-8'))

    unlinkSync(inputFile)
    unlinkSync(outputFile)

    return bytecode
}

export function formatBytecodeElement(el: any): string {
    if (typeof el === 'string') {
        return `'${el.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
    }
    return String(el)
}

export function formatBytecodeArray(bytecode: any[]): string {
    const elements = bytecode.map(formatBytecodeElement)
    const singleLine = `[${elements.join(', ')}]`

    if (singleLine.length + INDENT.length <= LINE_WIDTH) {
        return singleLine
    }

    // Multi-line: pack elements into lines of ~LINE_WIDTH chars
    const lines: string[] = []
    let currentLine = ''

    for (const el of elements) {
        const separator = currentLine ? ', ' : ''
        if (currentLine && currentLine.length + separator.length + el.length + INDENT.length > LINE_WIDTH) {
            lines.push(currentLine + ',')
            currentLine = el
        } else {
            currentLine += separator + el
        }
    }
    if (currentLine) {
        lines.push(currentLine + ',')
    }

    return '[\n' + lines.map((line) => INDENT + line).join('\n') + '\n    ]'
}

export function findProperty(node: ts.ObjectLiteralExpression, name: string): ts.PropertyAssignment | undefined {
    for (const prop of node.properties) {
        if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.name) && prop.name.text === name) {
            return prop
        }
    }
    return undefined
}

export function extractTemplateObject(sourceFile: ts.SourceFile): ts.ObjectLiteralExpression | undefined {
    let result: ts.ObjectLiteralExpression | undefined

    function visit(node: ts.Node): void {
        if (
            ts.isVariableDeclaration(node) &&
            ts.isIdentifier(node.name) &&
            node.name.text === 'template' &&
            node.initializer &&
            ts.isObjectLiteralExpression(node.initializer)
        ) {
            result = node.initializer
            return
        }
        // Also handle: export const template: Type = { ... } satisfies Type
        if (
            ts.isVariableDeclaration(node) &&
            ts.isIdentifier(node.name) &&
            node.name.text === 'template' &&
            node.initializer &&
            ts.isSatisfiesExpression(node.initializer) &&
            ts.isObjectLiteralExpression(node.initializer.expression)
        ) {
            result = node.initializer.expression
            return
        }
        ts.forEachChild(node, visit)
    }

    visit(sourceFile)
    return result
}

export function extractStringValue(node: ts.Expression): string | undefined {
    if (ts.isStringLiteral(node)) {
        return node.text
    }
    if (ts.isNoSubstitutionTemplateLiteral(node)) {
        return node.text
    }
    return undefined
}

export function processTemplate(filePath: string, compiler: (code: string) => any[] = compileHogCode): boolean {
    const source = readFileSync(filePath, 'utf-8')
    const sourceFile = ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true)

    const templateObj = extractTemplateObject(sourceFile)
    if (!templateObj) {
        console.error(`  ERROR: No 'template' object found in ${filePath}`)
        process.exitCode = 1
        return false
    }

    const codeProp = findProperty(templateObj, 'code')
    if (!codeProp) {
        console.error(`  ERROR: No 'code' property found in ${filePath}`)
        process.exitCode = 1
        return false
    }

    const codeValue = extractStringValue(codeProp.initializer)
    if (codeValue === undefined) {
        console.error(`  ERROR: Could not extract code string from ${filePath}`)
        process.exitCode = 1
        return false
    }

    const newBytecode = compiler(codeValue)
    const formatted = formatBytecodeArray(newBytecode)

    let newSource: string
    const bytecodeProp = findProperty(templateObj, 'bytecode')

    if (bytecodeProp) {
        // Replace existing bytecode value
        const initStart = bytecodeProp.initializer.getStart(sourceFile)
        const initEnd = bytecodeProp.initializer.getEnd()
        newSource = source.slice(0, initStart) + formatted + source.slice(initEnd)
    } else {
        // Insert bytecode property after the code property
        const codeEnd = codeProp.getEnd()
        const trailingComma = source[codeEnd] === ',' ? 1 : 0
        const insertPos = codeEnd + trailingComma
        newSource = source.slice(0, insertPos) + `\n    bytecode: ${formatted},` + source.slice(insertPos)
    }

    if (newSource === source) {
        return false
    }

    writeFileSync(filePath, newSource)
    return true
}

function main(): void {
    console.log('Compiling warehouse source template bytecode...\n')

    const files = readdirSync(TEMPLATES_DIR).filter((f) => f.endsWith('.template.ts') && !f.endsWith('.test.ts'))

    if (files.length === 0) {
        console.log('No template files found.')
        return
    }

    let updatedCount = 0

    for (const file of files) {
        const filePath = join(TEMPLATES_DIR, file)
        console.log(`  Processing ${file}...`)

        const changed = processTemplate(filePath)
        if (changed) {
            console.log(`    -> bytecode updated`)
            updatedCount++
        } else {
            console.log(`    -> up to date`)
        }
    }

    console.log(`\nDone. ${updatedCount} file(s) updated.`)
}

if (require.main === module) {
    main()
}
