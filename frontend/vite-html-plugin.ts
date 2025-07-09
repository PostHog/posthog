import type { Plugin } from 'vite'
import { readFileSync, writeFileSync } from 'fs'
import { resolve } from 'path'

export function htmlGenerationPlugin(): Plugin {
    return {
        name: 'html-generation',
        closeBundle() {
            generateHtml('src/index.html', 'dist/index.html', 'index')
            generateHtml('src/layout.html', 'dist/layout.html', 'index')
            generateHtml('src/exporter/index.html', 'dist/exporter.html', 'exporter')
        },
    }
}

function generateHtml(from: string, to: string, entry: string) {
    try {
        const htmlContent = readFileSync(resolve('.', from), 'utf-8')
        
        // Read the Vite manifest to get the correct asset URLs
        let manifestContent: any = {}
        try {
            const manifestPath = resolve('.', 'dist/.vite/manifest.json')
            manifestContent = JSON.parse(readFileSync(manifestPath, 'utf-8'))
        } catch (e) {
            console.warn('Could not read Vite manifest, falling back to basic script injection')
        }
        
        // Get the entry file from manifest
        const entryKey = `src/${entry}.tsx`
        const manifestEntry = manifestContent[entryKey]
        
        let scriptTag = ''
        if (manifestEntry && manifestEntry.file) {
            // Use Vite manifest for proper asset loading
            scriptTag = `<script type="module" crossorigin src="/static/${manifestEntry.file}"></script>`
            
            // Add any CSS files from the manifest
            if (manifestEntry.css && manifestEntry.css.length > 0) {
                const cssLinks = manifestEntry.css.map((cssFile: string) => 
                    `<link rel="stylesheet" crossorigin href="/static/${cssFile}">`
                ).join('\n    ')
                scriptTag = cssLinks + '\n    ' + scriptTag
            }
        } else {
            // Fallback to the old approach if manifest is not available
            const buildId = new Date().valueOf()
            scriptTag = `<script type="module">
window.ESBUILD_LOAD_SCRIPT = async function (file) {
    try {
        await import((window.JS_URL || '/static/') + file)
    } catch (error) {
        console.error('Error loading chunk: "' + file + '"')
        console.error(error)
    }
}
window.ESBUILD_LOAD_SCRIPT('${entry}.js?t=${buildId}')
</script>`
        }

        const modifiedHtml = htmlContent.replace(
            '</head>',
            `   ${scriptTag}
            </head>`
        )

        writeFileSync(resolve('.', to), modifiedHtml)
    } catch (error) {
        console.warn(`Could not generate ${to}:`, error)
    }
} 