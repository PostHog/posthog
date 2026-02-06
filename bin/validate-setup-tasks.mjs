#!/usr/bin/env node
/**
 * CI Script: Validates setup tasks configuration:
 *
 * 1. All SetupTaskId enum values are either:
 *    - Marked as completed somewhere in the codebase (using SetupTaskId.XYZ)
 *    - Marked as requiresManualCompletion in the task definition
 *
 * 2. All targetSelector data-attr values exist in the codebase
 *
 * This prevents:
 * - Defining setup tasks that are never actually completed anywhere
 * - Referencing data-attr selectors that no longer exist
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
    // Search for SetupTaskId.TaskName in the codebase, excluding the type definition and registry files
    // where the task is just being defined, not actually completed
    const pattern = `SetupTaskId\\.${taskId}`

    for (const searchPath of SEARCH_PATHS) {
        const fullPath = path.join(ROOT_DIR, searchPath)
        if (!fs.existsSync(fullPath)) {
            continue
        }

        try {
            execSync(
                // Safe: taskId is extracted from our own source code via regex matching only [A-Za-z]+ characters
                // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
                `grep -r "${pattern}" "${fullPath}" --include="*.ts" --include="*.tsx" --exclude="types.ts" --exclude="productSetupRegistry.ts" -q 2>/dev/null`,
                {
                    encoding: 'utf-8',
                }
            )
            return true
        } catch {
            // grep returns non-zero if no match found
        }
    }

    return false
}

function extractTargetSelectors() {
    const content = fs.readFileSync(REGISTRY_FILE, 'utf-8')

    // Find all targetSelector values with data-attr
    // Matches: targetSelector: '[data-attr="some-value"]'
    const selectorPattern = /targetSelector:\s*['"`]\[data-attr=["']([^"']+)["']\]['"`]/g
    const selectors = []
    let match

    while ((match = selectorPattern.exec(content)) !== null) {
        selectors.push(match[1])
    }

    return [...new Set(selectors)] // Remove duplicates
}

function findAllDataAttrsInCodebase() {
    // Run grep once to find ALL data-attr values in the codebase
    // This is much more efficient than running grep for each selector
    const foundAttrs = new Set()

    for (const searchPath of SEARCH_PATHS) {
        const fullPath = path.join(ROOT_DIR, searchPath)
        if (!fs.existsSync(fullPath)) {
            continue
        }

        try {
            // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
            // Safe: only searching our own source code with a fixed pattern
            const output = execSync(
                `grep -roh 'data-attr="[^"]*"' "${fullPath}" --include="*.ts" --include="*.tsx" 2>/dev/null || true`,
                { encoding: 'utf-8' }
            )

            // Extract the attribute values from matches like: data-attr="some-value"
            const matches = output.matchAll(/data-attr="([^"]*)"/g)
            for (const match of matches) {
                foundAttrs.add(match[1])
            }
        } catch {
            // Ignore errors
        }
    }

    return foundAttrs
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
    

    if (!fs.existsSync(TYPES_FILE)) {
        console.error(`ERROR: Types file not found at ${TYPES_FILE}`)
        process.exit(1)
    }

    if (!fs.existsSync(REGISTRY_FILE)) {
        console.error(`ERROR: Registry file not found at ${REGISTRY_FILE}`)
        process.exit(1)
    }

    let hasErrors = false

    // ========================================================================
    // Validate SetupTaskId completion
    // ========================================================================
    

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

    
    
    

    
    
    
    

    if (missingTasks.length > 0) {
        hasErrors = true
        console.error(`   ERROR: Missing task completion logic (${missingTasks.length}):\n`)
        for (const task of missingTasks) {
            console.error(`     - SetupTaskId.${task}`)
        }
        console.error('')
        console.error('   These SetupTaskId values are defined but neither:')
        console.error('     1. Used with markTaskAsCompleted() in the codebase')
        console.error('     2. Marked as requiresManualCompletion: true in the task definition')
        console.error('')
        console.error('   To fix:')
        console.error('     - Add completion logic where appropriate, OR')
        console.error('     - Add requiresManualCompletion: true to the task definition')
        console.error('')
    } else {
        
    }

    // ========================================================================
    // Validate targetSelector data-attrs exist
    // ========================================================================
    

    const selectors = extractTargetSelectors()
    const foundAttrs = findAllDataAttrsInCodebase()
    const missingSelectors = selectors.filter((selector) => !foundAttrs.has(selector))

    
    

    if (missingSelectors.length > 0) {
        hasErrors = true
        console.error(`\n   ERROR: Missing data-attr elements (${missingSelectors.length}):\n`)
        for (const selector of missingSelectors) {
            console.error(`     - data-attr="${selector}"`)
        }
        console.error('')
        console.error('   These data-attr values are referenced in targetSelector but not found in the codebase.')
        console.error('   The element may have been renamed or removed.')
        console.error('')
        console.error('   To fix:')
        console.error('     - Update the targetSelector to match an existing data-attr, OR')
        console.error('     - Add the data-attr to the appropriate element, OR')
        console.error('     - Remove the targetSelector if highlighting is no longer needed')
        console.error('')
    } else {
        
    }

    // ========================================================================
    // Final result
    // ========================================================================
    if (hasErrors) {
        console.error('Validation failed!')
        process.exit(1)
    }

    
}

main()
