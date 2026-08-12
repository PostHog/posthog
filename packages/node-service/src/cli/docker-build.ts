#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'

function findRepositoryRoot(start: string): string {
    let directory = resolve(start)
    while (true) {
        if (existsSync(resolve(directory, 'pnpm-workspace.yaml'))) {
            return directory
        }
        const parent = dirname(directory)
        if (parent === directory) {
            throw new Error('Could not find pnpm-workspace.yaml')
        }
        directory = parent
    }
}

function readPackageName(directory: string): string {
    const manifest = JSON.parse(readFileSync(resolve(directory, 'package.json'), 'utf8')) as unknown
    if (
        typeof manifest !== 'object' ||
        manifest === null ||
        !('name' in manifest) ||
        typeof manifest.name !== 'string'
    ) {
        throw new Error('package.json must contain a package name')
    }
    return manifest.name
}

function parseTag(args: string[], packageName: string): string {
    if (args.length === 0) {
        return `posthog-${packageName.split('/').at(-1)}`
    }
    if (args.length === 2 && args[0] === '--tag' && args[1]) {
        return args[1]
    }
    throw new Error('Usage: posthog-node-service-docker-build [--tag image-name]')
}

function main(): void {
    const serviceDirectory = process.cwd()
    const repositoryRoot = findRepositoryRoot(serviceDirectory)
    const packageName = readPackageName(serviceDirectory)
    const servicePath = relative(repositoryRoot, serviceDirectory)
    const tag = parseTag(process.argv.slice(2), packageName)
    const commit = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: repositoryRoot, encoding: 'utf8' }).stdout.trim()
    const result = spawnSync(
        'docker',
        [
            'build',
            '-f',
            resolve(repositoryRoot, 'packages/node-service/Dockerfile'),
            '--build-arg',
            `SERVICE_PACKAGE=${packageName}`,
            '--build-arg',
            `SERVICE_PATH=${servicePath}`,
            '--build-arg',
            `COMMIT_HASH=${commit || 'unknown'}`,
            '-t',
            tag,
            repositoryRoot,
        ],
        { stdio: 'inherit' }
    )
    if (result.error) {
        throw result.error
    }
    process.exitCode = result.status ?? 1
}

try {
    main()
} catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
}
