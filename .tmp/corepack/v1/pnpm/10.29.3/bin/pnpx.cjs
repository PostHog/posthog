#!/usr/bin/env node

process.argv = [...process.argv.slice(0, 2), 'dlx', ...process.argv.slice(2)]

require('./pnpm.cjs')
