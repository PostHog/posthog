import type { Plugin } from 'vite'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs'
import { resolve, dirname } from 'path'

function copyHtmlFile(from: string, to: string): void {
    try {
        const fromPath = resolve('.', from)
        const toPath = resolve('.', to)

        // Ensure target directory exists
        const toDir = dirname(toPath)
        if (!existsSync(toDir)) {
            mkdirSync(toDir, { recursive: true })
        }

        // Copy the HTML file without modification (preserve Django template syntax)
        const htmlContent = readFileSync(fromPath, 'utf-8')
        writeFileSync(toPath, htmlContent)
    } catch (error) {
        console.warn(`❌ Could not copy ${from} to ${to}:`, error)
    }
}

function generateHtmlFiles(): void {
    // Ensure dist directory exists
    const distDir = resolve('.', 'dist')
    if (!existsSync(distDir)) {
        mkdirSync(distDir, { recursive: true })
    }

    // Copy HTML files
    copyHtmlFile('src/index.html', 'dist/index.html')
    copyHtmlFile('src/layout.html', 'dist/layout.html')
    copyHtmlFile('src/exporter/index.html', 'dist/exporter.html')
}

export function htmlGenerationPlugin(): Plugin {
    return {
        name: 'html-generation',
        buildStart() {
            // Copy HTML files during build start for both dev and build
            generateHtmlFiles()
        },
        generateBundle() {
            // Also copy during bundle generation to ensure they're in dist for production
            generateHtmlFiles()
        },
    }
}
