const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')
const { relayArtifacts, retentionDays } = require('../actions/relay-master-artifacts/index.cjs')

async function fixture(t, names = ['migrated-schema', 'junit-results-backend-Core-1']) {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'backend-artifact-relay-'))
    t.after(() => fs.rm(directory, { recursive: true, force: true }))
    const destinationRoot = path.join(directory, 'artifacts')
    await fs.mkdir(destinationRoot)
    const root = await fs.realpath(destinationRoot)
    const manifestPath = path.join(directory, 'manifest.json')
    const manifest = []
    for (const name of names) {
        const destination = path.join(root, name)
        await fs.mkdir(destination)
        await fs.writeFile(path.join(destination, 'result.txt'), 'synthetic result')
        manifest.push({ name, path: destination })
    }
    await fs.writeFile(manifestPath, JSON.stringify(manifest))
    const calls = []
    const client = {
        async listArtifacts(options) {
            calls.push(['list', options])
            return { artifacts: [{ name: 'migrated-schema' }, { name: 'backend-master-owner' }] }
        },
        async deleteArtifact(name) {
            calls.push(['delete', name])
        },
        async uploadArtifact(...args) {
            calls.push(['upload', ...args])
        },
    }
    return { root, manifestPath, manifest, client, calls }
}

test('relay preserves artifact names, contents and retention without replacing owner receipts', async (t) => {
    const f = await fixture(t)
    await relayArtifacts(f)
    assert.deepEqual(f.calls, [
        ['list', { latest: true }],
        ['delete', 'migrated-schema'],
        [
            'upload',
            'migrated-schema',
            [path.join(f.root, 'migrated-schema/result.txt')],
            path.join(f.root, 'migrated-schema'),
            { retentionDays: 7 },
        ],
        [
            'upload',
            'junit-results-backend-Core-1',
            [path.join(f.root, 'junit-results-backend-Core-1/result.txt')],
            path.join(f.root, 'junit-results-backend-Core-1'),
            { retentionDays: undefined },
        ],
    ])
})

for (const name of [
    'backend-master-owner',
    'backend-master-dispatch',
    'backend-master-depot-binding',
    '../owner',
    'bad:name',
]) {
    test(`relay refuses ${name} before deleting or uploading any artifact`, async (t) => {
        const f = await fixture(t)
        f.manifest[1].name = name
        await fs.writeFile(f.manifestPath, JSON.stringify(f.manifest))
        await assert.rejects(relayArtifacts(f), /unsafe, reserved, or repeated/)
        assert.deepEqual(f.calls, [])
    })
}

for (const variation of ['duplicate', 'outside', 'link', 'empty']) {
    test(`relay rejects ${variation} entries before publishing the first valid artifact`, async (t) => {
        const f = await fixture(t)
        if (variation === 'duplicate') f.manifest[1] = f.manifest[0]
        if (variation === 'outside') f.manifest[1].path = path.dirname(f.root)
        if (variation === 'link') await fs.symlink(f.manifestPath, path.join(f.manifest[1].path, 'link'))
        if (variation === 'empty') await fs.unlink(path.join(f.manifest[1].path, 'result.txt'))
        await fs.writeFile(f.manifestPath, JSON.stringify(f.manifest))
        await assert.rejects(relayArtifacts(f))
        assert.deepEqual(f.calls, [])
    })
}

test('relay propagates upload failures instead of reporting a successful artifact bridge', async (t) => {
    const f = await fixture(t)
    f.client.uploadArtifact = async () => {
        throw new Error('Upload failed')
    }
    await assert.rejects(relayArtifacts(f), /Upload failed/)
})

test('retention follows canonical timing, recording and diagnostic artifact lifetimes', () => {
    for (const [name, days] of [
        ['test-durations-plan', 30],
        ['select-tests-output', 14],
        ['events-schema-record-Core-1-attempt2', 14],
        ['timing_data-Core-1', 2],
        ['email_renders-synthetic-1', 1],
        ['snapshot-patch-Products-1', 1],
        ['migration-analysis', undefined],
    ])
        assert.equal(retentionDays(name), days)
})
