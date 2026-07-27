#!/usr/bin/env node
import fs from 'node:fs'

import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const CONFIG = {
    sql: {
        id: 'django-migration-sql',
        legacyPrefixes: ['## Migration SQL Changes'],
    },
    risk: {
        id: 'django-migration-risk',
        legacyPrefixes: ['## 🔍 Migration Risk Analysis'],
    },
}

const [kind, mode, status, summary, bodyPath] = process.argv.slice(2)
const config = CONFIG[kind]
if (!config || !['post', 'clear'].includes(mode) || !summary || !bodyPath) {
    console.error('Usage: post-django-migration-section.mjs <sql|risk> <post|clear> <status> <summary> <body path>')
    process.exit(1)
}

const body = fs.readFileSync(bodyPath, 'utf8').trim()
const options = { legacyPrefixes: config.legacyPrefixes }
if (mode === 'clear') {
    await clearSectionIfPresent({ id: config.id, summary, body }, options)
} else {
    await postSection({ id: config.id, status, summary, body }, options)
}
