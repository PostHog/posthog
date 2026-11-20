import assert from 'node:assert/strict'
import test from 'node:test'

import { findAcknowledgement, fingerprintReasons, nativeInputs, rebuildReasons } from './mobile-rebuild.mjs'

const commit = 'a'.repeat(40)
const base = {
    build: {
        base: { node: '22.22.0' },
        production: { extends: 'base', channel: 'production' },
    },
    submit: {
        store: { ios: { ascAppId: '1234567890' } },
        production: { extends: 'store' },
    },
}

test('preview-only profiles leave the production build unchanged', () => {
    const head = structuredClone(base)
    head.build.preview = { extends: 'base', channel: 'preview' }
    head.submit.preview = { android: { track: 'internal' } }
    assert.deepEqual(rebuildReasons(['eas.json'], base, head), [])

    head.build.base.node = '22.22.1'
    assert.deepEqual(rebuildReasons(['eas.json'], base, head), ['Production EAS build profile changed'])
})

test('an inherited production submission destination requires acknowledgement', () => {
    const head = structuredClone(base)
    head.submit.store.ios.ascAppId = '2345678901'
    assert.deepEqual(rebuildReasons(['eas.json'], base, head), ['Production EAS submission profile changed'])
})

test('build configuration and install inputs require acknowledgement before a fingerprint is calculated', () => {
    for (const file of [
        'app.config.ts',
        'plugins/withAndroidDisplayName.js',
        'package.json',
        'pnpm-lock.yaml',
        'patches/dependency.patch',
    ]) {
        const paths = nativeInputs([`products/mobile/${file}`])
        assert.deepEqual(
            rebuildReasons(paths, base, base),
            ['Mobile build configuration or dependencies changed'],
            file
        )
    }
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
    assert.deepEqual(rebuildReasons(paths, base, base), [
        'Production build packaging or toolchain changed',
        'Tracked native project files changed',
    ])
})

test('asset fingerprints report the affected platform and reject incomplete results', () => {
    const hashes = { ios: 'a'.repeat(40), android: 'b'.repeat(40) }
    assert.deepEqual(fingerprintReasons(hashes, hashes), [])
    assert.deepEqual(fingerprintReasons(hashes, { ...hashes, android: 'c'.repeat(40) }), [
        'Android native fingerprint changed',
    ])
    assert.throws(() => fingerprintReasons(hashes, { ios: hashes.ios }), /Missing production fingerprint for Android/)
})
test('an iOS widget change requires acknowledgement even with identical production fingerprints', () => {
    const paths = nativeInputs(['products/mobile/targets/HedgehogWidget/ChartFetcher.swift'])
    assert.deepEqual(rebuildReasons(paths, base, base), ['iOS extension target files changed'])
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
