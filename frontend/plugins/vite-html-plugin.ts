import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'fs'
import { dirname, resolve } from 'path'
import type { Plugin } from 'vite'

const srcHtmlFiles = [
    'src/index.html',
    'src/layout.html',
    'src/exporter/index.html',
    'src/render-query/index.html',
    '../products/tasks/frontend/infrastructure/infrastructureAdmin.html',
    '../products/agent_transcripts/frontend/viewer/transcriptViewer.html',
]
const distHtmlFiles = [
    'dist/index.html',
    'dist/layout.html',
    'dist/exporter.html',
    'dist/render_query.html',
    'dist/infrastructure_admin.html',
    'dist/agent_transcript_viewer.html',
]
// Standalone staff pages that Django serves, and the entry each one mounts from the Vite dev server.
const adminPageEntries: Record<string, string> = {
    'dist/infrastructure_admin.html': '../products/tasks/frontend/infrastructure/mountInfrastructureAdmin.tsx',
    'dist/agent_transcript_viewer.html': '../products/agent_transcripts/frontend/viewer/mountTranscriptViewer.tsx',
}

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

        const htmlContent = readFileSync(fromPath, 'utf-8')
        const adminPageEntry = adminPageEntries[to]
        const content = adminPageEntry
            ? htmlContent.replace(
                  '</head>',
                  `<script type="module" nonce="{{ request.csp_nonce }}">
            import RefreshRuntime from '{{ js_url|escapejs }}/@react-refresh'
            RefreshRuntime.injectIntoGlobalHook(window)
            window.$RefreshReg$ = () => {}
            window.$RefreshSig$ = () => (type) => type
            window.__vite_plugin_react_preamble_installed__ = true
        </script><script type="module" src="{{ js_url }}/@vite/client"></script><script type="module" src="{{ js_url }}/@fs${resolve(adminPageEntry)}"></script></head>`
              )
            : htmlContent
        writeFileSync(toPath, content)
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
    srcHtmlFiles.forEach((file, index) => {
        copyHtmlFile(file, distHtmlFiles[index])
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
