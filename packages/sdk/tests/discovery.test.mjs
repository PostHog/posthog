import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

import { runCli } from '../dist/cli.js'
import { catalog, describeTool, searchTools } from '../dist/discovery.js'

const sources = new Map()
async function source(file) {
    if (!sources.has(file)) {
        const text = await fs.readFile(new URL(`../${file}`, import.meta.url), 'utf8')
        sources.set(file, { text, parsed: ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true) })
    }
    return sources.get(file)
}

test('offline discovery points to explicit input and output interfaces in source and declarations', async (t) => {
    t.mock.method(globalThis, 'fetch', () => assert.fail('discovery must stay offline'))
    const guide = runCli(['--agent-help'])
    assert.match(guide, /^# PostHog SDK guide for agents/)
    assert.match(guide, /npx @posthog\/sdk describe queries\.trends/)
    assert.match(guide, /`client\.dataCatalog\.metricList`/)
    assert.doesNotMatch(guide, /\{[a-z_]+\}|posthog:exec|`(?:info|call|exec search) /)
    const methods = new Set(catalog.tools.map((tool) => tool.method))
    for (const [, method] of guide.matchAll(/`client\.([\w.]+)`/g)) {
        assert.ok(methods.has(method), `Agent help must refer to an exported method: ${method}`)
    }
    const mcp = JSON.parse(
        await fs.readFile(new URL('../../../services/mcp/schema/tool-definitions-all.json', import.meta.url), 'utf8')
    )
    assert.deepEqual(catalog.tools.map((tool) => tool.toolName).sort(), Object.keys(mcp).sort())
    const coverage = JSON.parse(await fs.readFile(new URL('../coverage.json', import.meta.url), 'utf8'))
    assert.equal(coverage.length, catalog.tools.length)
    assert.ok(coverage.every((entry) => entry.status === 'exported'))
    for (const entry of catalog.tools) {
        const tool = describeTool(entry.method)
        const onDisk = JSON.parse(await fs.readFile(new URL(`../${entry.descriptionFile}`, import.meta.url), 'utf8'))
        assert.deepEqual(tool, onDisk)
        for (const reference of [tool.input, tool.output]) {
            for (const file of [reference.source, reference.declaration]) {
                const { parsed } = await source(file)
                const declaration = parsed.statements.find((node) => node.name?.text === reference.name)
                assert.ok(declaration, `${file} must declare ${reference.name}`)
                if (!ts.isInterfaceDeclaration(declaration)) {
                    assert.ok(
                        ts.isTypeAliasDeclaration(declaration) && ts.isUnionTypeNode(declaration.type),
                        `${reference.name} must be an interface or a union of named interfaces`
                    )
                    for (const member of declaration.type.types) {
                        assert.ok(ts.isTypeReferenceNode(member), `${reference.name} must name its union variants`)
                        assert.ok(
                            parsed.statements.some(
                                (node) =>
                                    ts.isInterfaceDeclaration(node) &&
                                    node.name.text === member.typeName.getText(parsed)
                            ),
                            `${reference.name} variants must be grep-able interfaces`
                        )
                    }
                }
            }
        }
        for (const reference of tool.referencedTypes) {
            const { parsed } = await source(reference.declaration)
            assert.ok(
                parsed.statements.some((node) => node.name?.text === reference.name),
                `${reference.name} must be shipped`
            )
        }
        const methodSource = await source(tool.methodSource)
        const methodDeclaration = await source(tool.methodSource.replace(/^src\//, 'dist/').replace(/\.ts$/, '.d.ts'))
        for (const layer of tool.methodDocumentation) {
            const normalized = (value) =>
                value
                    .replace(/\*\//g, '* /')
                    .replace(/^\s*\*(?: |$)/gm, '')
                    .replace(/\s+/g, ' ')
                    .trim()
            assert.ok(
                normalized(methodSource.text).includes(normalized(layer.text)),
                `${tool.method} source preserves ${layer.role} description`
            )
            assert.ok(
                normalized(methodDeclaration.text).includes(normalized(layer.text)),
                `${tool.method} declarations preserve ${layer.role} description`
            )
        }
    }
})

test('search and describe preserve MCP names, overrides, and nested comments without exposing mutable catalog state', async () => {
    assert.equal(searchTools('archive feature flag')[0].method, 'featureFlags.archive')
    assert.equal(describeTool('feature-flag-archive').method, 'featureFlags.archive')
    assert.match(runCli(['describe', 'featureFlags.archive']), /export interface FeatureFlagsArchiveOutput/)
    assert.equal(JSON.parse(runCli(['describe', 'queries.trends', '--json'])).input.name, 'QueriesTrendsInput')
    assert.throws(() => runCli(['describe', 'missing.method']), /Unknown SDK method/)
    const list = describeTool('featureFlags.list')
    const docs = list.typeDocumentation.find((entry) => entry.typeName === list.input.name && entry.field === 'active')
    assert.deepEqual(
        docs.layers.map(({ role }) => role),
        ['original', 'override']
    )
    assert.equal(docs.layers[0].source.kind, 'openapi')
    assert.equal(docs.layers[1].source.kind, 'mcp_yaml')
    for (const file of [list.input.source, list.input.declaration]) {
        const { text } = await source(file)
        for (const layer of docs.layers) {
            assert.ok(text.includes(layer.text))
        }
    }
    const trends = describeTool('queries.trends')
    assert.ok(
        trends.typeDocumentation.some((entry) =>
            entry.layers.some(
                (layer) => layer.source.kind === 'query_schema' && layer.source.pointer.startsWith('#/definitions/')
            )
        )
    )
    list.requiredScopes.push('invented:scope')
    assert.equal(describeTool('featureFlags.list').requiredScopes.includes('invented:scope'), false)
})
