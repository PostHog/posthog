import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'fs'
import { dirname, resolve } from 'path'
import type { Plugin } from 'vite'

const distHtmlFiles = ['dist/index.html', 'dist/layout.html']

const srcHtmlFiles = ['src/index.html', 'src/layout.html']

function deleteHtmlFiles(): void {
    distHtmlFiles.forEach((file) => {
        try {
            const filePath = resolve('.', file)
            if (existsSync(filePath)) {
                unlinkSync(filePath)
                console.info(`🗑️  Deleted ${file}`)
            } else {
                console.info(`ℹ️  File doesn't exist: ${file}`)
            }
        } catch (error) {
            console.warn(`⚠️ Could not delete ${file}:`, error)
        }
    })
}

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
        console.info(`✨ Copied ${from} to ${to}`)
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
    srcHtmlFiles.forEach((file) => {
        copyHtmlFile(file, `dist/${file.replace('src/', '')}`)
    })
}

export function htmlGenerationPlugin(): Plugin {
    return {
        name: 'html-generation',
        buildStart() {
            deleteHtmlFiles()
            generateHtmlFiles()
        },
    }
}
