import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

import { runCli } from '../dist/cli.js'
import { domains, operations } from '../dist/discovery.js'

async function registry(file) {
    const text = await fs.readFile(new URL(`../${file}`, import.meta.url), 'utf8')
    const parsed = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true)
    return {
        text,
        parsed,
        declarations: new Map(parsed.statements.filter((node) => node.name).map((node) => [node.name.text, node])),
    }
}

function rows(text) {
    const [header, ...lines] = text.replace(/\n$/, '').split('\n')
    const columns = header.split('\t')
    return lines.map((line) => {
        const cells = line.split('\t')
        assert.equal(cells.length, columns.length)
        return Object.fromEntries(columns.map((column, index) => [column, cells[index]]))
    })
}

const normalized = (value) =>
    value
        .replace(/\*\//g, '* /')
        .replace(/^\s*\*(?: |$)/gm, '')
        .replace(/\s+/g, ' ')
        .trim()

test('offline help and indexes expose every registered method and resolvable contracts in one registry', async (t) => {
    t.mock.method(globalThis, 'fetch', () => assert.fail('discovery must stay offline'))
    const guide = runCli(['--agent-help'])
    const readDefinitions = async (name) =>
        JSON.parse(await fs.readFile(new URL('../../../services/mcp/schema/' + name + '.json', import.meta.url)))
    const mcp = {
        ...(await readDefinitions('tool-definitions')),
        ...(await readDefinitions('generated-tool-definitions')),
    }
    assert.deepEqual(operations.map((op) => op.toolName).sort(), Object.keys(mcp).sort())
    assert.match(guide, /Available tool domains/)
    assert.ok(guide.includes('featureFlags'))
    assert.ok(guide.includes(fileURLToPath(new URL('../src/generated/api.ts', import.meta.url))))
    const coverage = JSON.parse(await fs.readFile(new URL('../coverage.json', import.meta.url), 'utf8'))
    assert.deepEqual(
        coverage.map(({ toolName, method }) => ({ toolName, method })).sort((a, b) => a.method.localeCompare(b.method)),
        operations.map(({ toolName, method }) => ({ toolName, method }))
    )
    assert.ok(coverage.every((entry) => entry.status === 'exported'))
    const index = rows(await fs.readFile(new URL('../api-index.tsv', import.meta.url), 'utf8'))
    assert.equal(index.length, operations.length)
    for (const [position, operation] of operations.entries()) {
        for (const [column, value] of Object.entries(index[position])) {
            const expected = Array.isArray(operation[column]) ? operation[column].join(',') : String(operation[column])
            assert.equal(value, expected.replace(/[\t\r\n]+/g, ' '))
        }
    }
    assert.deepEqual(
        rows(await fs.readFile(new URL('../domains.tsv', import.meta.url), 'utf8')),
        domains.map((domain) => ({ ...domain, methods: String(domain.methods) }))
    )
    for (const file of ['src/generated/api.ts', 'dist/generated/api.d.ts']) {
        const { parsed, declarations } = await registry(file)
        const client = declarations.get('GeneratedClient')
        assert.ok(ts.isInterfaceDeclaration(client))
        assert.deepEqual(
            client.members.map((member) => member.name.text),
            domains.map(({ domain }) => domain)
        )
        for (const operation of operations) {
            for (const name of [operation.input, operation.output]) {
                const declaration = declarations.get(name)
                assert.ok(declaration, `${file} must declare ${name}`)
            }
            const [domain, method] = operation.method.split('.')
            const domainClient = declarations.get(`${domain[0].toUpperCase()}${domain.slice(1)}Client`)
            const signature = domainClient.members.find((member) => member.name.text === method)
            assert.equal(signature.parameters[0].type.getText(parsed), operation.input)
            assert.match(signature.getFullText(parsed), new RegExp(`@mcpTool ${operation.toolName}\\b`))
            assert.ok(
                normalized(signature.getFullText(parsed)).includes(normalized(mcp[operation.toolName].description))
            )
        }
    }
})

test('API registry preserves original comments, overrides, and host guidance while CLI directs discovery to rg', async () => {
    for (const file of ['src/generated/api.ts', 'dist/generated/api.d.ts']) {
        const { parsed, declarations, text } = await registry(file)
        const flags = declarations.get('FeatureFlagsListInput').getFullText(parsed)
        assert.match(flags, /@sourceDescription/)
        assert.match(flags, /active/)
        assert.match(text, /@mcpTool query-trends/)
        assert.ok(declarations.has('QueriesTrendsInput'))
    }
    for (const args of [
        ['search', 'feature flag'],
        ['describe', 'signals.scoutRunsList'],
        ['list', '--json'],
    ]) {
        assert.throws(() => runCli(args), /Search api-index.tsv and src\/generated\/api.ts with grep or rg/)
    }
})
