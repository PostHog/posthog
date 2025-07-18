import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import type { Plugin } from 'vite'
const execAsync = promisify(exec)

export function keaTypegenPlugin(): Plugin {
    let isRunning = false
    let lastRun = 0
    const debounceMs = 100 // Debounce multiple rapid file changes

    return {
        name: 'kea-typegen',
        configureServer(server) {
            // Watch for logic file changes
            server.ws.on('file-changed', async (file) => {
                // Only process logic files
                if (!file.includes('Logic.ts') && !file.includes('Logic.tsx')) {
                    return
                }

                const now = Date.now()
                if (isRunning || now - lastRun < debounceMs) {
                    return
                }

                isRunning = true
                lastRun = now

                try {
                    // Run kea-typegen from the project root (parent of frontend)
                    await execAsync(
                        'NODE_OPTIONS="--max-old-space-size=16384" npx kea-typegen write --delete --show-ts-errors --use-cache',
                        {
                            cwd: path.resolve(process.cwd(), '..'),
                            timeout: 30000,
                        }
                    )

                    // Trigger HMR update for the generated type file
                    const typeFile = file.replace(/Logic\.(ts|tsx)$/, 'LogicType.ts')
                    if (typeFile !== file) {
                        server.ws.send({
                            type: 'update',
                            updates: [
                                {
                                    type: 'js-update',
                                    path: typeFile,
                                    acceptedPath: typeFile,
                                    timestamp: Date.now(),
                                },
                            ],
                        })
                    }
                } catch (error: any) {
                    console.error('❌ Kea typegen failed:', error.message)
                } finally {
                    isRunning = false
                }
            })
        },

        // Alternative approach using handleHotUpdate hook
        handleHotUpdate(ctx) {
            const { file } = ctx

            // Only process logic files
            if (!file.includes('Logic.ts') && !file.includes('Logic.tsx')) {
                return
            }

            // Use setTimeout to debounce and run after the initial HMR
            setTimeout(async () => {
                const now = Date.now()
                if (isRunning || now - lastRun < debounceMs) {
                    return
                }

                isRunning = true
                lastRun = now

                try {
                    await execAsync(
                        'NODE_OPTIONS="--max-old-space-size=16384" npx kea-typegen write --delete --show-ts-errors --use-cache',
                        {
                            cwd: path.resolve(process.cwd(), '..'),
                            timeout: 30000,
                        }
                    )
                } catch (error: any) {
                    console.error('❌ Kea typegen failed:', error.message)
                } finally {
                    isRunning = false
                }
            }, 50) // Small delay to let the initial HMR complete first
        },
    }
}
