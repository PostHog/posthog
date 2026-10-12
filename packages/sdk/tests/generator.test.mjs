import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
    annotateDocumentation,
    resolveSdkOperation,
    SchemaRegistry,
} from '../../../services/mcp/scripts/lib/sdk-schema.mjs'
import { SdkTypeRegistry } from '../../../services/mcp/scripts/lib/sdk-type-registry.mjs'
import { Runtime } from '../dist/runtime/client.js'

function fixture(method = 'patch') {
    const spec = {
        paths: {
            '/api/projects/{project_id}/examples/{id}/': {
                [method]: {
                    operationId: 'examples_update',
                    description: 'Original method documentation.',
                    parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'integer' } }],
                    requestBody: {
                        content: { 'application/json': { schema: { $ref: '#/components/schemas/Example' } } },
                    },
                    responses: {
                        200: { content: { 'application/json': { schema: { $ref: '#/components/schemas/Example' } } } },
                    },
                },
            },
        },
        components: {
            schemas: {
                Nested: {
                    type: 'object',
                    properties: {
                        label: { type: 'string', description: 'Original nested label.' },
                        secret: { type: 'string' },
                    },
                    required: ['label', 'secret'],
                },
                Example: {
                    allOf: [
                        {
                            type: 'object',
                            properties: {
                                key: { type: 'string', description: 'Original key.', default: 'untitled' },
                                server_id: { type: 'integer', readOnly: true },
                                password: { type: 'string', writeOnly: true },
                            },
                            required: ['server_id'],
                        },
                        {
                            type: 'object',
                            properties: {
                                nested: { $ref: '#/components/schemas/Nested' },
                                maybe: { type: 'string', enum: ['one', 'two'], nullable: true },
                                items: { type: 'array', items: { $ref: '#/components/schemas/Nested' } },
                                values: { type: 'array', items: { type: ['string', 'null'] } },
                            },
                            required: ['nested', 'items', 'maybe', 'values'],
                        },
                    ],
                },
            },
        },
    }
    annotateDocumentation(spec, { kind: 'openapi', file: 'fixture.json' })
    return spec
}

const config = {
    sdk: { namespace: 'examples', method: 'update' },
    operation: 'examples_update',
    scopes: ['example:write'],
    description: 'Tool method documentation.',
    rename_params: { key: 'name' },
    param_overrides: { key: { description: 'Overridden key.', default: 'default override' } },
    response: { exclude: ['nested.secret', 'items.*.secret'], strip_nulls: true },
}
const resolve = (spec, overrides = {}) =>
    resolveSdkOperation(
        spec,
        { ...config, ...overrides },
        { category: 'Examples' },
        'example-update',
        '/repo/examples/tools.yaml',
        '/repo'
    )

test('shared resolution keeps comments, PATCH omission, directionality, and nested projection aligned with runtime', async () => {
    const operation = resolve(fixture())
    const source = operation.registry.schemas.ExamplesUpdateInput.properties.name
    assert.equal(source.description, 'Overridden key.')
    assert.equal(source['x-source-description'], 'Original key.')
    assert.equal(source['x-documentation-source'].pointer, '#/components/schemas/Example/allOf/0/properties/key')
    assert.deepEqual(
        operation.documentation.layers.map(({ text }) => text),
        ['Original method documentation.', 'Tool method documentation.']
    )
    const runtime = new Runtime({
        env: false,
        token: 'phx_example',
        projectId: 8,
        fetch: async (_url, init) => {
            const body = JSON.parse(init.body)
            assert.equal(Object.hasOwn(body, 'key'), false)
            assert.equal(Object.hasOwn(body, 'server_id'), false)
            assert.equal(body.password, 'example-password')
            return Response.json({
                server_id: 2,
                key: 'example',
                nested: { label: 'one', secret: 'not returned' },
                items: [{ label: 'two', secret: 'not returned' }],
                maybe: null,
                values: ['one', null],
            })
        },
    })
    const result = await runtime.execute(operation.definition, {
        id: 5,
        password: 'example-password',
        nested: { label: 'one', secret: 'example' },
        items: [],
        maybe: null,
        values: [],
    })
    assert.deepEqual(result.data, {
        server_id: 2,
        key: 'example',
        nested: { label: 'one' },
        items: [{ label: 'two' }],
        values: ['one', null],
    })
    assert.equal(operation.registry.schemas.ExamplesUpdateData.properties.password, undefined)
    assert.equal(operation.registry.schemas.ExamplesUpdateData.required.includes('maybe'), false)
})

test('selectable fields are optional but cannot escape the generated allowlist', async () => {
    const operation = resolve(fixture(), {
        response: { include: ['server_id', 'nested.label'], selectable: true },
        param_overrides: {},
    })
    assert.deepEqual(operation.registry.schemas.ExamplesUpdateData.required, [])
    const input = {
        id: 5,
        nested: { label: 'one', secret: 'example' },
        items: [],
        maybe: 'one',
        values: [],
        fields: ['nested.label'],
    }
    const runtime = new Runtime({
        env: false,
        token: 'phx_example',
        projectId: 8,
        fetch: async () => Response.json({ server_id: 2, nested: { label: 'one', secret: 'hidden' } }),
    })
    assert.deepEqual((await runtime.execute(operation.definition, input)).data, { nested: { label: 'one' } })
    await assert.rejects(
        runtime.execute(operation.definition, { ...input, fields: ['nested.secret'] }),
        (error) => error.details.kind === 'input_validation'
    )
})

test('multiple success statuses include empty responses without weakening the root output interface', async () => {
    const spec = fixture()
    spec.paths['/api/projects/{project_id}/examples/{id}/'].patch.responses[204] = { description: 'No content.' }
    const operation = resolve(spec, { response: {} })
    assert.equal(operation.registry.schemas.ExamplesUpdateOutput.type, 'object')
    const runtime = new Runtime({
        env: false,
        token: 'phx_example',
        projectId: 8,
        fetch: async () => new Response(null, { status: 204 }),
    })
    const result = await runtime.execute(operation.definition, {
        id: 5,
        nested: { label: 'one', secret: 'example' },
        items: [],
        maybe: null,
        values: [],
    })
    assert.deepEqual(result, { data: null, meta: { status: 204 } })
})

test('capabilities needing an adapter cannot be opted in by adding an SDK name', () => {
    for (const override of [
        { hooks: { beforeRequest: 'custom' } },
        { soft_delete: true },
        { feature_flag: 'example-gate' },
        { confirmed_action: { message: 'Confirm' } },
    ]) {
        assert.throws(() => resolve(fixture(), override), /adapter/)
    }
    assert.throws(
        () => resolve(fixture(), { response: { include: ['invented_field'] } }),
        /absent from its source schema/
    )
    const spec = fixture()
    spec.paths['/api/projects/{project_id}/examples/{id}/'].patch['x-internal'] = true
    assert.throws(() => resolve(spec), /x-internal/)
})

test('shared registry merges recursive contracts while preserving nested overrides and request variants', () => {
    const spec = {
        components: {
            schemas: {
                Parent: { type: 'object', properties: { child: { $ref: '#/components/schemas/Child' } } },
                Child: {
                    type: 'object',
                    properties: {
                        parent: { $ref: '#/components/schemas/Parent' },
                        value: { type: 'string', default: 'example', description: 'Original field.' },
                        server: { type: 'string', readOnly: true },
                    },
                },
            },
        },
    }
    const make = (prefix, direction = 'input', options = {}) => {
        const registry = new SchemaRegistry(spec, prefix)
        registry.add(`${prefix}Input`, { $ref: '#/components/schemas/Parent' }, direction, options)
        return { registry }
    }
    const first = make('First')
    const same = make('Same')
    const changed = make('Changed')
    changed.registry.schemas.ChangedRequestChild.properties.value.description = 'Override field.'
    const response = make('Response', 'output')
    const patch = make('Patch', 'input', { patch: true })
    const { schemas, aliases } = new SdkTypeRegistry([first, same, changed, response, patch]).merge()
    assert.equal(aliases.get('SameRequestChild'), 'FirstRequestChild')
    assert.equal(aliases.get('SameRequestParent'), 'FirstRequestParent')
    assert.ok(schemas.FirstInput && schemas.SameInput)
    assert.ok(schemas.ChangedRequestChild && schemas.ChangedRequestParent)
    assert.equal(schemas.ChangedRequestParent.properties.child.$ref, '#/components/schemas/ChangedRequestChild')
    assert.equal(schemas.ResponseResponseChild.properties.server.type, 'string')
    assert.equal(schemas.FirstRequestChild.properties.server, undefined)
    assert.equal(schemas.PatchRequestChild.properties.value.default, undefined)
    assert.equal(schemas.FirstRequestChild.properties.value.default, 'example')
})
