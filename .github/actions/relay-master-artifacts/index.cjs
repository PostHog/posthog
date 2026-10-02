const fs = require('node:fs/promises')
const path = require('node:path')

const RESERVED = new Set(['backend-master-owner', 'backend-master-dispatch', 'backend-master-depot-binding'])

function retentionDays(name) {
    if (name === 'migrated-schema') return 7
    if (name === 'test-durations-plan') return 30
    if (name === 'select-tests-output' || name.startsWith('events-schema-record-')) return 14
    if (name.startsWith('timing_data-') || name.startsWith('coverage-') || name === 'patch-coverage') return 2
    if (name.startsWith('snapshot-patch-') || name.startsWith('email_renders-')) return 1
    if (name.startsWith('test-selection-verdict-')) return 90
    return undefined
}

async function filesIn(directory) {
    const files = []
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
        const filename = path.join(directory, entry.name)
        if (entry.isDirectory()) {
            files.push(...(await filesIn(filename)))
        } else if (entry.isFile()) {
            files.push(filename)
        } else {
            throw new Error('Artifact contains a link or special file')
        }
    }
    return files.sort()
}

async function relayArtifacts({ manifestPath, root, client }) {
    const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
    if (!Array.isArray(manifest) || manifest.length > 256) throw new Error('Invalid artifact manifest')
    const resolvedRoot = await fs.realpath(root)
    const names = new Set()
    const prepared = []
    for (const entry of manifest) {
        if (
            !entry ||
            typeof entry.name !== 'string' ||
            typeof entry.path !== 'string' ||
            !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$/.test(entry.name) ||
            RESERVED.has(entry.name) ||
            names.has(entry.name)
        ) {
            throw new Error('Artifact name is unsafe, reserved, or repeated')
        }
        names.add(entry.name)
        const directory = path.join(resolvedRoot, entry.name)
        if ((await fs.realpath(entry.path)) !== directory)
            throw new Error('Artifact path is outside the relay directory')
        if ((await fs.lstat(entry.path)).isSymbolicLink()) throw new Error('Artifact directory is a link')
        const files = await filesIn(directory)
        if (!files.length) throw new Error('Cannot republish an empty artifact')
        prepared.push({ name: entry.name, directory, files })
    }
    if (!prepared.length) return
    const existing = new Set((await client.listArtifacts({ latest: true })).artifacts.map((artifact) => artifact.name))
    for (const artifact of prepared) {
        // Rerunning the relay republishes the same owner's data, never its immutable receipts.
        if (existing.has(artifact.name)) await client.deleteArtifact(artifact.name)
        await client.uploadArtifact(artifact.name, artifact.files, artifact.directory, {
            retentionDays: retentionDays(artifact.name),
        })
    }
}

module.exports = { relayArtifacts, retentionDays }
