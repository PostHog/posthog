#!/usr/bin/env node
import { spawn } from 'node:child_process'

function run(command, args, options = {}) {
    return spawn(command, args, {
        stdio: 'inherit',
        shell: false,
        ...options,
    })
}

const prism = run('pnpm', [
    '--filter=@posthog/root',
    'exec',
    'prism',
    'proxy',
    'http://localhost:8000/api/schema/?format=json',
    'http://localhost:8000',
    '--errors',
    '--port',
    '4010',
])

const cleanup = () => {
    if (!prism.killed) {
        prism.kill('SIGTERM')
    }
}

process.on('SIGINT', cleanup)
process.on('SIGTERM', cleanup)
process.on('exit', cleanup)

setTimeout(() => {
    const playwright = run(
        'pnpm',
        [
            '--filter=@posthog/playwright',
            'exec',
            'playwright',
            'test',
            'e2e/product-analytics/openapi-contract.spec.ts',
        ],
        {
            env: {
                ...process.env,
                BASE_URL: 'http://localhost:4010',
            },
        }
    )

    playwright.on('exit', (code) => {
        cleanup()
        process.exit(code ?? 1)
    })
}, 4000)

prism.on('exit', (code) => {
    if (code && code !== 0) {
        process.exit(code)
    }
})
