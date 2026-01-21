#!/usr/bin/env node
/**
 * CI Script: Validates that all SetupTaskId enum values are either:
 * 1. Marked as completed somewhere in the codebase (using SetupTaskId.XYZ)
 * 2. Marked as requiresManualCompletion in the task definition
 *
 * This prevents defining setup tasks that are never actually completed anywhere.
 *
 * Usage: node bin/validate-setup-tasks.mjs
 */

import * as fs from 'fs'
import * as path from 'path'
import { execSync } from 'child_process'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const ROOT_DIR = path.resolve(__dirname, '..')
const TYPES_FILE = path.join(ROOT_DIR, 'frontend/src/lib/components/ProductSetup/types.ts')
const REGISTRY_FILE = path.join(ROOT_DIR, 'frontend/src/lib/components/ProductSetup/productSetupRegistry.ts')
const SEARCH_PATHS = ['frontend/src', 'products']

function extractSetupTaskIds() {
    const content = fs.readFileSync(TYPES_FILE, 'utf-8')

    // Find the SetupTaskId enum
    const enumMatch = content.match(/export enum SetupTaskId \{([\s\S]*?)\n\}/)
    if (!enumMatch) {
        console.error('ERROR: Could not find SetupTaskId enum in types.ts')
        process.exit(1)
    }

    const enumBody = enumMatch[1]
    const taskIds = []

    // Match lines like: TaskName = 'task_name',
    const lines = enumBody.split('\n')
    for (const line of lines) {
        const match = line.match(/^\s+([A-Za-z]+)\s*=/)
        if (match) {
            taskIds.push(match[1])
        }
    }

    return taskIds
}

function checkTaskHasCompletionCode(taskId) {
    // Search for SetupTaskId.TaskName in the codebase
    const pattern = `SetupTaskId\\.${taskId}`

    for (const searchPath of SEARCH_PATHS) {
        const fullPath = path.join(ROOT_DIR, searchPath)
        if (!fs.existsSync(fullPath)) {
            continue
        }

        try {
            // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
            // Safe: taskId is extracted from our own source code via regex matching only [A-Za-z]+ characters
            execSync(`grep -r "${pattern}" "${fullPath}" --include="*.ts" --include="*.tsx" -q 2>/dev/null`, {
                encoding: 'utf-8',
            })
            return true
        } catch {
            // grep returns non-zero if no match found
        }
    }

    return false
}

function checkTaskRequiresManualCompletion(taskId) {
    const content = fs.readFileSync(REGISTRY_FILE, 'utf-8')

    // Look for the task definition with requiresManualCompletion: true
    // We need to find the task block that contains SetupTaskId.TaskName and check if it has requiresManualCompletion: true

    const taskPattern = new RegExp(`id:\\s*SetupTaskId\\.${taskId}[,\\s]`, 'g')
    let match

    while ((match = taskPattern.exec(content)) !== null) {
        // Get the surrounding context (the object definition)
        // Find the opening brace before this match
        let braceDepth = 0
        let startIndex = match.index

        // Go backwards to find the opening brace
        for (let i = match.index; i >= 0; i--) {
            if (content[i] === '}') {
                braceDepth++
            }
            if (content[i] === '{') {
                if (braceDepth === 0) {
                    startIndex = i
                    break
                }
                braceDepth--
            }
        }

        // Go forward to find the closing brace
        braceDepth = 0
        let endIndex = match.index
        for (let i = startIndex; i < content.length; i++) {
            if (content[i] === '{') {
                braceDepth++
            }
            if (content[i] === '}') {
                braceDepth--
                if (braceDepth === 0) {
                    endIndex = i + 1
                    break
                }
            }
        }

        const taskBlock = content.slice(startIndex, endIndex)

        // Check if this task block has requiresManualCompletion: true
        if (/requiresManualCompletion:\s*true/.test(taskBlock)) {
            return true
        }
    }

    return false
}

function main() {
    console.log('Validating SetupTaskId usage in codebase...\n')

    if (!fs.existsSync(TYPES_FILE)) {
        console.error(`ERROR: Types file not found at ${TYPES_FILE}`)
        process.exit(1)
    }

    if (!fs.existsSync(REGISTRY_FILE)) {
        console.error(`ERROR: Registry file not found at ${REGISTRY_FILE}`)
        process.exit(1)
    }

    const taskIds = extractSetupTaskIds()
    const tasks = []
    const missingTasks = []

    for (const taskId of taskIds) {
        const hasCompletionCode = checkTaskHasCompletionCode(taskId)
        const requiresManualCompletion = checkTaskRequiresManualCompletion(taskId)

        tasks.push({
            name: taskId,
            hasCompletionCode,
            requiresManualCompletion,
        })

        // Task is valid if it either has completion code OR requires manual completion
        if (!hasCompletionCode && !requiresManualCompletion) {
            missingTasks.push(taskId)
        }
    }

    const totalCount = tasks.length
    const manualCount = tasks.filter((t) => t.requiresManualCompletion).length
    const autoCount = tasks.filter((t) => t.hasCompletionCode && !t.requiresManualCompletion).length

    console.log(`Found ${totalCount} SetupTaskId values in types.ts`)
    console.log(`  - ${manualCount} require manual completion (user marks done)`)
    console.log(`  - ${autoCount} have auto-completion code`)
    console.log('')

    if (missingTasks.length > 0) {
        console.error(`ERROR: Missing task validation (${missingTasks.length}):\n`)
        for (const task of missingTasks) {
            console.error(`  - SetupTaskId.${task}`)
        }
        console.error('')
        console.error('These SetupTaskId values are defined but neither:')
        console.error('  1. Used with markTaskAsCompleted() in the codebase')
        console.error('  2. Marked as requiresManualCompletion: true in the task definition')
        console.error('')
        console.error('To fix:')
        console.error('  - Add completion logic where appropriate, OR')
        console.error('  - Add requiresManualCompletion: true to the task definition in productSetupRegistry.ts')
        process.exit(1)
    }

    const validatedCount = totalCount
    console.log(`All ${validatedCount} tasks are properly validated.`)
    console.log('Validation passed!')
}

main()
