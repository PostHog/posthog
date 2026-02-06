#!/usr/bin/env node

/**
 * Runs Jest tests only for files that have changed relative to a base branch.
 * Uses Jest's --findRelatedTests to run tests affected by the changed files.
 *
 * Usage:
 *   node scripts/jest-changed-tests.js [--base <branch>] [--dry-run] [-- <jest-args>]
 *
 * Options:
 *   --base <branch>  Base branch to compare against (default: origin/master)
 *   --dry-run        Show detected files without running tests
 *
 * Examples:
 *   node scripts/jest-changed-tests.js
 *   node scripts/jest-changed-tests.js --dry-run
 *   node scripts/jest-changed-tests.js --base origin/main
 *   node scripts/jest-changed-tests.js -- --coverage
 */

const { execSync, spawn } = require('child_process')
const path = require('path')

const REPO_ROOT = path.resolve(__dirname, '../..')
const FRONTEND_ROOT = path.resolve(__dirname, '..')

const RELEVANT_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx']
const RELEVANT_DIRS = ['frontend/', 'products/', 'common/']

function parseArgs() {
    const args = process.argv.slice(2)
    let baseBranch = 'origin/master'
    let jestArgs = []
    let dryRun = false

    const separatorIndex = args.indexOf('--')
    const ourArgs = separatorIndex >= 0 ? args.slice(0, separatorIndex) : args
    jestArgs = separatorIndex >= 0 ? args.slice(separatorIndex + 1) : []

    for (let i = 0; i < ourArgs.length; i++) {
        if (ourArgs[i] === '--base' && ourArgs[i + 1]) {
            baseBranch = ourArgs[i + 1]
            i++
        } else if (ourArgs[i] === '--dry-run') {
            dryRun = true
        }
    }

    return { baseBranch, jestArgs, dryRun }
}

function getChangedFiles(baseBranch) {
    try {
        // Get files changed since the base branch (staged + unstaged + committed)
        const diffOutput = execSync(`git diff --name-only ${baseBranch}...HEAD`, {
            cwd: REPO_ROOT,
            encoding: 'utf-8',
        }).trim()

        // Also get uncommitted changes (staged and unstaged)
        const uncommittedOutput = execSync('git diff --name-only HEAD', {
            cwd: REPO_ROOT,
            encoding: 'utf-8',
        }).trim()

        const stagedOutput = execSync('git diff --name-only --cached', {
            cwd: REPO_ROOT,
            encoding: 'utf-8',
        }).trim()

        const allFiles = new Set([
            ...diffOutput.split('\n').filter(Boolean),
            ...uncommittedOutput.split('\n').filter(Boolean),
            ...stagedOutput.split('\n').filter(Boolean),
        ])

        return [...allFiles]
    } catch (error) {
        console.error('Error getting changed files from git:', error.message)
        process.exit(1)
    }
}

function filterRelevantFiles(files) {
    return files.filter((file) => {
        const ext = path.extname(file)
        const isRelevantExtension = RELEVANT_EXTENSIONS.includes(ext)
        const isInRelevantDir = RELEVANT_DIRS.some((dir) => file.startsWith(dir))
        const isNotTest = !file.includes('.test.') && !file.includes('.spec.') && !file.includes('__tests__')

        return isRelevantExtension && isInRelevantDir && isNotTest
    })
}

function runJestWithRelatedTests(files, jestArgs) {
    const absolutePaths = files.map((file) => path.resolve(REPO_ROOT, file))

    const args = ['--findRelatedTests', '--passWithNoTests', ...absolutePaths, ...jestArgs]

    const jest = spawn('npx', ['jest', ...args], {
        cwd: FRONTEND_ROOT,
        stdio: 'inherit',
        shell: true,
    })

    jest.on('close', (code) => {
        process.exit(code)
    })

    jest.on('error', (error) => {
        console.error('Failed to run Jest:', error.message)
        process.exit(1)
    })
}

function main() {
    const { baseBranch, jestArgs, dryRun } = parseArgs()

    const changedFiles = getChangedFiles(baseBranch)
    const relevantFiles = filterRelevantFiles(changedFiles)

    if (dryRun) {
        changedFiles.forEach((file) => {
            console.log(`Changed: ${file}`)
        })

        relevantFiles.forEach((file) => {
            console.log(`Relevant: ${file}`)
        })
        process.exit(0)
    }

    if (relevantFiles.length === 0) {
        process.exit(0)
    }

    runJestWithRelatedTests(relevantFiles, jestArgs)
}

main()
