import { existsSync, mkdirSync, readFileSync, readdirSync, rmdirSync, statSync, unlinkSync, writeFileSync } from 'fs'
import { dirname, join, relative, resolve } from 'path'
import type { Plugin } from 'vite'

function deleteDirectory(dirPath: string): void {
    try {
        const files = readdirSync(dirPath, { withFileTypes: true })
        files.forEach((file) => {
            const filePath = join(dirPath, file.name)
            if (file.isDirectory()) {
                deleteDirectory(filePath)
            } else {
                unlinkSync(filePath)
            }
        })
        // Remove the empty directory
        rmdirSync(dirPath)
    } catch (error) {
        console.warn(`⚠️ Could not delete directory ${dirPath}:`, error)
    }
}

// Skip the copy when the destination already matches the source (same size, not older).
// These trees are megabytes of images; rewriting them on every dev-server boot is pure
// startup cost.
function copyFileIfStale(from: string, to: string): boolean {
    try {
        const fromStat = statSync(from)
        try {
            const toStat = statSync(to)
            if (toStat.size === fromStat.size && toStat.mtimeMs >= fromStat.mtimeMs) {
                return false
            }
        } catch {
            // Destination missing — copy it
        }
        const toDir = dirname(to)
        if (!existsSync(toDir)) {
            mkdirSync(toDir, { recursive: true })
        }
        writeFileSync(to, readFileSync(from))
        return true
    } catch (error) {
        console.warn(`❌ Could not copy ${from} to ${to}:`, error)
        return false
    }
}

// One-way sync: copy stale/missing files from `from` into `to`, and remove entries in
// `to` that no longer exist in `from` (the destination is fully derived from the source).
function syncDirectory(from: string, to: string): number {
    let copied = 0
    try {
        if (!existsSync(to)) {
            mkdirSync(to, { recursive: true })
        }

        const sourceEntries = readdirSync(from, { withFileTypes: true })
        const sourceNames = new Set<string>()
        sourceEntries.forEach((entry) => {
            // Skip .DS_Store files
            if (entry.name === '.DS_Store') {
                return
            }
            sourceNames.add(entry.name)
            const fromPath = join(from, entry.name)
            const toPath = join(to, entry.name)
            if (entry.isDirectory()) {
                copied += syncDirectory(fromPath, toPath)
            } else if (copyFileIfStale(fromPath, toPath)) {
                copied += 1
            }
        })

        // Prune destination entries that are gone from the source
        readdirSync(to, { withFileTypes: true }).forEach((entry) => {
            if (entry.name === '.DS_Store' || sourceNames.has(entry.name)) {
                return
            }
            const orphanPath = join(to, entry.name)
            if (entry.isDirectory()) {
                deleteDirectory(orphanPath)
            } else {
                unlinkSync(orphanPath)
            }
        })
    } catch (error) {
        console.warn(`❌ Could not sync directory ${from} to ${to}:`, error)
    }
    return copied
}

function copyPublicAssets(): void {
    const publicDir = resolve('.', 'public')
    const assetsDir = resolve('.', 'src/assets')

    if (existsSync(publicDir)) {
        const copied = syncDirectory(publicDir, assetsDir)
        console.info(`✅ Synced public assets to src/assets (${copied} file(s) copied)`)
    } else {
        console.warn('⚠️ Public directory does not exist')
    }

    // Copy hedgehog-mode assets to dist
    const hedgehogModeSrc = resolve('.', 'node_modules', '@posthog', 'hedgehog-mode', 'assets')
    const hedgehogModeDest = resolve('.', 'dist', 'hedgehog-mode')
    if (existsSync(hedgehogModeSrc)) {
        const copied = syncDirectory(hedgehogModeSrc, hedgehogModeDest)
        console.info(`✅ Synced hedgehog-mode assets to dist/hedgehog-mode (${copied} file(s) copied)`)
    } else {
        console.warn('⚠️ Hedgehog-mode assets directory does not exist')
    }
}

export function publicAssetsPlugin(): Plugin {
    return {
        name: 'public-assets-copy',
        configureServer() {
            // Sync assets when dev server starts
            copyPublicAssets()
        },
        handleHotUpdate({ file }) {
            // If a file in public directory changes, re-copy it to assets
            const publicDir = resolve('.', 'public')
            if (file.startsWith(publicDir)) {
                const relativePath = relative(publicDir, file)
                const targetPath = resolve('.', 'src/assets', relativePath)

                if (existsSync(file)) {
                    copyFileIfStale(file, targetPath)
                }
            }
        },
    }
}
