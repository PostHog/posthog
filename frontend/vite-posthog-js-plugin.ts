import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'fs'
import { dirname, join, resolve } from 'path'
import type { Plugin } from 'vite'

function copyFile(from: string, to: string): void {
    try {
        // Ensure target directory exists
        const toDir = dirname(to)
        if (!existsSync(toDir)) {
            mkdirSync(toDir, { recursive: true })
        }

        // Copy the file
        const fileContent = readFileSync(from)
        writeFileSync(to, fileContent)
    } catch (error) {
        // Silently fail if file doesn't exist (matches copy-posthog-js script behavior)
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
            console.warn(`❌ Could not copy ${from} to ${to}:`, error)
        }
    }
}

function copyPostHogJsFiles(): void {
    const nodeModulesPostHogJs = resolve('.', 'node_modules/posthog-js/dist')
    const distDir = resolve('.', 'dist')

    // Ensure dist directory exists
    if (!existsSync(distDir)) {
        mkdirSync(distDir, { recursive: true })
    }

    // Copy specific files (matching frontend/bin/copy-posthog-js)
    const filesToCopy = [
        'array.js',
        'array.js.map',
        'array.full.js',
        'array.full.js.map',
        'array.full.es5.js',
        'array.full.es5.js.map',
        'surveys.js',
        'surveys.js.map',
        'exception-autocapture.js',
        'exception-autocapture.js.map',
        'web-vitals.js',
        'web-vitals.js.map',
        'tracing-headers.js',
        'tracing-headers.js.map',
        'dead-clicks-autocapture.js',
        'dead-clicks-autocapture.js.map',
        'customizations.full.js',
        'customizations.full.js.map',
        'product-tours.js',
        'product-tours.js.map',
    ]

    filesToCopy.forEach((file) => {
        const from = join(nodeModulesPostHogJs, file)
        const to = join(distDir, file)
        copyFile(from, to)
    })

    // Copy integration files (e.g., *integration.js*)
    try {
        const files = readdirSync(nodeModulesPostHogJs)
        files.forEach((file: string) => {
            if (file.includes('integration') && (file.endsWith('.js') || file.endsWith('.js.map'))) {
                const from = join(nodeModulesPostHogJs, file)
                const to = join(distDir, file)
                copyFile(from, to)
            }
        })
    } catch (error) {
        console.warn(`❌ Could not copy integration files:`, error)
    }

    // Copy recorder files (e.g., *recorder*.js*)
    try {
        const files = readdirSync(nodeModulesPostHogJs)
        files.forEach((file: string) => {
            if (file.includes('recorder') && (file.endsWith('.js') || file.endsWith('.js.map'))) {
                const from = join(nodeModulesPostHogJs, file)
                const to = join(distDir, file)
                copyFile(from, to)
            }
        })
    } catch (error) {
        console.warn(`❌ Could not copy recorder files:`, error)
    }

    console.info('✅ Copied posthog-js files to dist/')
}

export function posthogJsPlugin(): Plugin {
    return {
        name: 'posthog-js-copy',
        configureServer() {
            // Copy posthog-js files when dev server starts
            copyPostHogJsFiles()
        },
        buildStart() {
            // Also copy when building
            copyPostHogJsFiles()
        },
    }
}
