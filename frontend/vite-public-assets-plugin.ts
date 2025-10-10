import { existsSync, mkdirSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from 'fs'
import { dirname, join, relative, resolve } from 'path'
import type { Plugin } from 'vite'

function deleteAssetsFiles(): void {
    try {
        const assetsPath = resolve('.', 'src/assets')
        if (existsSync(assetsPath)) {
            // Remove all files in assets directory except .DS_Store
            const files = readdirSync(assetsPath, { withFileTypes: true })
            files.forEach((file) => {
                if (file.name !== '.DS_Store') {
                    const filePath = join(assetsPath, file.name)
                    if (file.isDirectory()) {
                        // Recursively delete directory
                        deleteDirectory(filePath)
                    } else {
                        unlinkSync(filePath)
                    }
                }
            })
        }
    } catch (error) {
        console.warn(`⚠️ Could not clean assets directory:`, error)
    }
}

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
        require('fs').rmdirSync(dirPath)
    } catch (error) {
        console.warn(`⚠️ Could not delete directory ${dirPath}:`, error)
    }
}

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
        console.warn(`❌ Could not copy ${from} to ${to}:`, error)
    }
}

function copyDirectory(from: string, to: string): void {
    try {
        // Ensure target directory exists
        if (!existsSync(to)) {
            mkdirSync(to, { recursive: true })
        }

        const files = readdirSync(from, { withFileTypes: true })
        files.forEach((file) => {
            // Skip .DS_Store files
            if (file.name === '.DS_Store') {
                return
            }

            const fromPath = join(from, file.name)
            const toPath = join(to, file.name)

            if (file.isDirectory()) {
                copyDirectory(fromPath, toPath)
            } else {
                copyFile(fromPath, toPath)
            }
        })
    } catch (error) {
        console.warn(`❌ Could not copy directory ${from} to ${to}:`, error)
    }
}

function copyPublicAssets(): void {
    const publicDir = resolve('.', 'public')
    const assetsDir = resolve('.', 'src/assets')

    // Ensure assets directory exists
    if (!existsSync(assetsDir)) {
        mkdirSync(assetsDir, { recursive: true })
    }

    // Copy all files and directories from public to assets
    if (existsSync(publicDir)) {
        copyDirectory(publicDir, assetsDir)
        console.info('✅ Copied public assets to src/assets')
    } else {
        console.warn('⚠️ Public directory does not exist')
    }
}

export function publicAssetsPlugin(): Plugin {
    return {
        name: 'public-assets-copy',
        configureServer() {
            // Copy assets when dev server starts
            deleteAssetsFiles()
            copyPublicAssets()
        },
        handleHotUpdate({ file }) {
            // If a file in public directory changes, re-copy it to assets
            const publicDir = resolve('.', 'public')
            if (file.startsWith(publicDir)) {
                const relativePath = relative(publicDir, file)
                const targetPath = resolve('.', 'src/assets', relativePath)

                if (existsSync(file)) {
                    copyFile(file, targetPath)
                }
            }
        },
    }
}
