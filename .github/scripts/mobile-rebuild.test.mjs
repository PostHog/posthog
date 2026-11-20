import assert from 'node:assert/strict'
import test from 'node:test'

import { findAcknowledgement, nativeInputs, rebuildReasons } from './mobile-rebuild.mjs'

const commit = 'a'.repeat(40)
const base = {
    hashes: { ios: 'b'.repeat(40), android: 'c'.repeat(40) },
    eas: {
        build: {
            base: { node: '22.22.0' },
            production: { extends: 'base', channel: 'production' },
        },
    },
}

test('preview-only profiles leave the production build unchanged', () => {
    const head = structuredClone(base)
    head.eas.build.preview = { extends: 'base', channel: 'preview' }
    assert.deepEqual(rebuildReasons(['eas.json'], base, head), [])

    head.eas.build.base.node = '22.22.1'
    assert.deepEqual(rebuildReasons(['eas.json'], base, head), ['Production EAS build profile changed'])
})

test('native changes are reported even when Expo omits an input from the fingerprint', () => {
    const paths = nativeInputs([
        'products/mobile/android/app/build.gradle',
        'products/mobile/modules/hedgehog-widget/android/src/test/WidgetTest.kt',
        'products/mobile/modules/hedgehog-widget/src/index.ts',
        'products/mobile/app/(tabs)/screen.tsx',
        'products/mobile/.easignore',
    ])
    assert.deepEqual(paths, ['android/app/build.gradle', '.easignore'])
    const head = { ...base, hashes: { ...base.hashes, android: 'd'.repeat(40) } }
    assert.deepEqual(rebuildReasons(paths, base, head), [
        'Android native fingerprint changed',
        'Production build packaging or toolchain changed',
        'Tracked native project files changed',
    ])
})

test('only a human maintainer can acknowledge the current commit, including the PR author', async () => {
    const command = `/ack-mobile-rebuild ${commit}`
    const comments = [
        { body: `/ack-mobile-rebuild ${'b'.repeat(40)}`, user: { login: 'pr-author', type: 'User' } },
        { body: command, user: { login: 'external-contributor', type: 'User' } },
        { body: command, user: { login: 'release-bot', type: 'Bot' } },
    ]
    const canWrite = async (login) => login !== 'external-contributor'
    assert.equal(await findAcknowledgement(comments, commit, canWrite), null)
    comments.push({ body: command, user: { login: 'pr-author', type: 'User' } })
    assert.equal(await findAcknowledgement(comments, commit, canWrite), 'pr-author')
})
