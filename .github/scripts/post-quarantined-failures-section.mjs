#!/usr/bin/env node
// Posts the quarantined-failures section of the shared CI report. A shard still goes green
// when Trunk has quarantined every failing test, so a regression in a quarantined test passes
// CI unseen. The section is warn-only and never fails a job.
//
// Usage: node post-quarantined-failures-section.mjs <junit-dir>
// Env: DJANGO_RESULT and TURBO_RESULT are the `needs.<job>.result` values of the test jobs.
//
// A failure in the JUnit may be a real one when a test job failed, so the section stays as it
// is. When every test job passed or was skipped, every remaining failure was quarantined.
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { markdownCell } from '../../frontend/bin/ci-report/format.mjs'
import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'quarantined-failures'
const MAX_ROWS = 50
const PASSING_RESULTS = new Set(['success', 'skipped'])

const INTRO =
    'These tests failed on this run, and Trunk quarantined them, so their shards still passed. A quarantine can outlive the flake that caused it and hide a real regression. Check each test below against your change, and say in the PR description why a failure does not apply.'

const XML_ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }

function unescapeXml(value) {
    return value.replace(/&(?:#(\d+)|#x([0-9a-fA-F]+)|(\w+));/g, (match, dec, hex, name) => {
        if (dec) {
            return String.fromCodePoint(Number(dec))
        }
        if (hex) {
            return String.fromCodePoint(parseInt(hex, 16))
        }
        return XML_ENTITIES[name] ?? match
    })
}

function parseAttributes(text) {
    const attributes = {}
    for (const [, key, value] of text.matchAll(/([\w:.-]+)\s*=\s*"([^"]*)"/g)) {
        attributes[key] = unescapeXml(value)
    }
    return attributes
}

/**
 * Returns the ids of the tests that have a failure or an error in a pytest JUnit report.
 * Tests in different classes can share a file and a name, so a passing entry never hides a failing one.
 */
export function failedTestIds(xml) {
    // pytest JUnit has no DTD or entities. Refuse a report that does, as the backend gate does.
    if (!/<(failure|error)\b/.test(xml) || /<!DOCTYPE|<!ENTITY/.test(xml)) {
        return []
    }
    const ids = new Set()
    for (const match of xml.matchAll(/<testcase\b([^>]*?)(\/>|>([\s\S]*?)<\/testcase>)/g)) {
        if (!/<(failure|error)\b/.test(match[3] ?? '')) {
            continue
        }
        const attributes = parseAttributes(match[1])
        const file = attributes.file || attributes.classname || ''
        ids.add([file, attributes.name ?? ''].filter(Boolean).join('::'))
    }
    return [...ids]
}

/**
 * Reads every JUnit file under `dir`, whose first path segment is the artifact name, and
 * returns one `{ shard, test }` row per failed test.
 */
export function collectFailures(dir) {
    const rows = []
    const artifacts = fs.existsSync(dir) ? fs.readdirSync(dir, { withFileTypes: true }) : []
    for (const artifact of artifacts.filter((entry) => entry.isDirectory())) {
        const files = fs
            .readdirSync(path.join(dir, artifact.name), { recursive: true })
            .filter((file) => /(^|\/)junit-[^/]*\.xml$/.test(file))
        for (const file of files) {
            const product = /^junit-product-(.+)\.xml$/.exec(path.basename(file))?.[1]
            const shard = product ? `products/${product}` : artifact.name.replace(/^junit-results-backend-/, '')
            const xml = fs.readFileSync(path.join(dir, artifact.name, file), 'utf8')
            for (const test of failedTestIds(xml)) {
                rows.push({ shard, test })
            }
        }
    }
    return rows.sort((a, b) => a.shard.localeCompare(b.shard) || a.test.localeCompare(b.test))
}

function count(number, noun) {
    return `${number} ${noun}${number === 1 ? '' : 's'}`
}

export function buildQuarantinedFailuresSection(failures) {
    const shards = new Set(failures.map((failure) => failure.shard)).size
    const lines = [INTRO, '', '| Shard | Test |', '| --- | --- |']
    for (const failure of failures.slice(0, MAX_ROWS)) {
        lines.push(`| ${markdownCell(failure.shard)} | \`${markdownCell(failure.test)}\` |`)
    }
    if (failures.length > MAX_ROWS) {
        lines.push(
            '',
            `${count(failures.length - MAX_ROWS, 'more quarantined failure')} not shown. See the shard JUnit artifacts.`
        )
    }
    return {
        status: 'warn',
        summary: `${count(failures.length, 'quarantined failure')} in ${count(shards, 'shard')}`,
        body: lines.join('\n'),
    }
}

export function testJobsPassed(results) {
    return results.every((result) => PASSING_RESULTS.has(result))
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    const dir = process.argv[2]
    if (!dir) {
        console.error('Usage: post-quarantined-failures-section.mjs <junit-dir>')
        process.exit(1)
    }
    if (!testJobsPassed([process.env.DJANGO_RESULT, process.env.TURBO_RESULT])) {
        console.info('A test job did not pass, so a failure may be a real one. Leaving the section untouched.')
    } else {
        const failures = collectFailures(dir)
        if (failures.length > 0) {
            await postSection({ id: SECTION_ID, ...buildQuarantinedFailuresSection(failures) })
        } else {
            await clearSectionIfPresent({
                id: SECTION_ID,
                summary: 'no quarantined test failed',
                body: 'No test failed on this run.',
            })
        }
    }
}
