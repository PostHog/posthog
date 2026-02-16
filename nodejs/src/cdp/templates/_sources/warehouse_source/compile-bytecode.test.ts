import { mkdtempSync, readFileSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import ts from 'typescript'

import {
    extractStringValue,
    extractTemplateObject,
    findProperty,
    formatBytecodeArray,
    formatBytecodeElement,
    processTemplate,
} from './compile-bytecode'

describe('compile-bytecode', () => {
    describe('formatBytecodeElement', () => {
        it.each([
            ['wraps strings in single quotes', '_H', "'_H'"],
            ['leaves numbers as-is', 42, '42'],
            ['leaves negative numbers as-is', -104, '-104'],
            ['escapes single quotes in strings', "it's", "'it\\'s'"],
            ['escapes backslashes in strings', 'back\\slash', "'back\\\\slash'"],
        ])('%s', (_label, input, expected) => {
            expect(formatBytecodeElement(input)).toBe(expected)
        })
    })

    describe('formatBytecodeArray', () => {
        it('formats short arrays on a single line', () => {
            const result = formatBytecodeArray(['_H', 1, 32, 'body'])
            expect(result).toBe("['_H', 1, 32, 'body']")
        })

        it('formats long arrays across multiple lines', () => {
            const longArray = Array.from({ length: 50 }, (_, i) => `element_${i}`)
            const result = formatBytecodeArray(longArray)

            expect(result).toMatch(/^\[/)
            expect(result).toMatch(/\]$/)
            expect(result.split('\n').length).toBeGreaterThan(1)
            // Each content line should be indented with 8 spaces
            for (const line of result.split('\n').slice(1, -1)) {
                expect(line).toMatch(/^        /)
            }
        })
    })

    describe('extractTemplateObject', () => {
        it('finds a plain object literal export', () => {
            const source = 'export const template = { code: "hello", bytecode: [] }'
            const sf = ts.createSourceFile('test.ts', source, ts.ScriptTarget.Latest, true)
            const obj = extractTemplateObject(sf)
            expect(obj).toBeDefined()
            expect(obj!.properties.length).toBe(2)
        })

        it('finds a typed object literal export', () => {
            const source = 'export const template: SomeType = { code: "hello" }'
            const sf = ts.createSourceFile('test.ts', source, ts.ScriptTarget.Latest, true)
            expect(extractTemplateObject(sf)).toBeDefined()
        })

        it('returns undefined when no template variable exists', () => {
            const source = 'export const other = { code: "hello" }'
            const sf = ts.createSourceFile('test.ts', source, ts.ScriptTarget.Latest, true)
            expect(extractTemplateObject(sf)).toBeUndefined()
        })
    })

    describe('findProperty', () => {
        it('finds a named property', () => {
            const source = 'const template = { code: "hello", bytecode: [] }'
            const sf = ts.createSourceFile('test.ts', source, ts.ScriptTarget.Latest, true)
            const obj = extractTemplateObject(sf)!
            expect(findProperty(obj, 'code')).toBeDefined()
            expect(findProperty(obj, 'bytecode')).toBeDefined()
            expect(findProperty(obj, 'missing')).toBeUndefined()
        })
    })

    describe('extractStringValue', () => {
        it.each([
            ['single-quoted string', "const x = 'hello'", 'hello'],
            ['double-quoted string', 'const x = "hello"', 'hello'],
            ['template literal', 'const x = `hello`', 'hello'],
        ])('extracts from %s', (_label, source, expected) => {
            const sf = ts.createSourceFile('test.ts', source, ts.ScriptTarget.Latest, true)
            const decl = sf.statements[0] as ts.VariableStatement
            const init = (decl.declarationList.declarations[0] as ts.VariableDeclaration).initializer!
            expect(extractStringValue(init)).toBe(expected)
        })
    })

    describe('processTemplate', () => {
        let tempDir: string

        beforeEach(() => {
            tempDir = mkdtempSync(join(tmpdir(), 'compile-bytecode-test-'))
        })

        const mockCompiler = (code: string): any[] => {
            if (code.includes('return request.body')) {
                return ['_H', 1, 32, 'body', 32, 'request', 1, 2, 38]
            }
            return ['_H', 1, 'compiled']
        }

        it('updates existing bytecode', () => {
            const filePath = join(tempDir, 'test.template.ts')
            writeFileSync(
                filePath,
                `export const template = {
    code: \`return request.body\`,
    bytecode: ['old'],
}`
            )

            const changed = processTemplate(filePath, mockCompiler)
            expect(changed).toBe(true)

            const result = readFileSync(filePath, 'utf-8')
            expect(result).toContain("'_H', 1, 32, 'body'")
            expect(result).not.toContain("'old'")
        })

        it('inserts bytecode when missing', () => {
            const filePath = join(tempDir, 'test.template.ts')
            writeFileSync(
                filePath,
                `export const template = {
    code: \`return request.body\`,
    inputs_schema: [],
}`
            )

            const changed = processTemplate(filePath, mockCompiler)
            expect(changed).toBe(true)

            const result = readFileSync(filePath, 'utf-8')
            expect(result).toContain('bytecode:')
            expect(result).toContain("'_H', 1, 32, 'body'")
        })

        it('returns false when bytecode is already up to date', () => {
            const filePath = join(tempDir, 'test.template.ts')
            writeFileSync(
                filePath,
                `export const template = {
    code: \`return request.body\`,
    bytecode: ['_H', 1, 32, 'body', 32, 'request', 1, 2, 38],
}`
            )

            const changed = processTemplate(filePath, mockCompiler)
            expect(changed).toBe(false)
        })

        it('returns false and sets exitCode when template object is missing', () => {
            const filePath = join(tempDir, 'test.template.ts')
            writeFileSync(filePath, 'export const other = {}')

            process.exitCode = undefined as any
            const changed = processTemplate(filePath, mockCompiler)
            expect(changed).toBe(false)
            expect(process.exitCode).toBe(1)
        })

        it('returns false and sets exitCode when code property is missing', () => {
            const filePath = join(tempDir, 'test.template.ts')
            writeFileSync(filePath, 'export const template = { bytecode: [] }')

            process.exitCode = undefined as any
            const changed = processTemplate(filePath, mockCompiler)
            expect(changed).toBe(false)
            expect(process.exitCode).toBe(1)
        })
    })
})
