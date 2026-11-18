import { getCookie } from 'lib/api'

import { getTerminalAiCreateUrl } from 'products/posthog_ai/frontend/generated/api'

import { FilesystemError, TerminalFilesystem } from './terminalFilesystem'

interface Generation {
    id: string
    controller: AbortController
    body: string
    status: number
    done: boolean
    error?: string
}

export class TerminalAI {
    private generation?: Generation
    private encoder = new TextEncoder()
    private decoder = new TextDecoder('utf-8', { fatal: true })

    constructor(filesystem: TerminalFilesystem, projectId: string, signal: AbortSignal) {
        const directory = filesystem.directory('.ai', filesystem.root)
        filesystem.file('response', directory, async () => {
            const generation = this.generation
            const bytes = this.encoder.encode(
                JSON.stringify(
                    generation
                        ? {
                              id: generation.id,
                              body: generation.body,
                              status: generation.status,
                              done: generation.done,
                              error: generation.error,
                          }
                        : { id: null, done: true }
                )
            )
            if (generation) {
                generation.body = ''
            }
            return { bytes }
        })
        filesystem.file(
            'request',
            directory,
            async () => ({
                bytes: new Uint8Array(),
                save: async (bytes) => {
                    if (signal.aborted) {
                        throw new DOMException('The terminal stopped.', 'AbortError')
                    }
                    if (this.generation && !this.generation.done) {
                        throw new FilesystemError(16)
                    }
                    if (bytes.length > 1024 * 1024) {
                        throw new Error('The conversation exceeds 1 MiB. Start a new pi session.')
                    }
                    const request = JSON.parse(this.decoder.decode(bytes))
                    if (typeof request.id !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(request.id) || !request.body) {
                        throw new Error('Invalid pi request. Start a new pi session.')
                    }
                    const generation: Generation = {
                        id: request.id,
                        controller: new AbortController(),
                        body: '',
                        status: 0,
                        done: false,
                    }
                    this.generation = generation
                    // A pending 9P save blocks other writes, including cancellation and pi's tools.
                    void this.stream(projectId, request.body, generation, signal)
                },
            }),
            true
        )
        filesystem.file(
            'cancel',
            directory,
            async () => ({
                bytes: new Uint8Array(),
                save: async (bytes) => {
                    if (this.decoder.decode(bytes) === this.generation?.id) {
                        this.generation.controller.abort()
                    }
                },
            }),
            true
        )
    }

    private async stream(projectId: string, body: unknown, generation: Generation, signal: AbortSignal): Promise<void> {
        const idle = new AbortController()
        let idleTimer = setTimeout(() => idle.abort(), 120_000)
        try {
            const response = await fetch(getTerminalAiCreateUrl(projectId), {
                method: 'POST',
                credentials: 'same-origin',
                redirect: 'error',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('posthog_csrftoken') || '',
                },
                body: JSON.stringify(body),
                signal: AbortSignal.any([signal, generation.controller.signal, idle.signal]),
            })
            generation.status = response.status
            const reader = response.body?.getReader()
            if (!reader) {
                throw new Error('PostHog AI returned no response. Try again.')
            }
            const decoder = new TextDecoder()
            let size = 0
            try {
                while (true) {
                    const chunk = await reader.read()
                    clearTimeout(idleTimer)
                    idleTimer = setTimeout(() => idle.abort(), 120_000)
                    if (chunk.done) {
                        generation.body += decoder.decode()
                        break
                    }
                    size += chunk.value.length
                    if (size > 2 * 1024 * 1024) {
                        throw new Error('The model response is too large. Ask for a shorter response.')
                    }
                    generation.body += decoder.decode(chunk.value, { stream: true })
                }
            } finally {
                try {
                    await reader.cancel()
                } finally {
                    reader.releaseLock()
                }
            }
        } catch (error) {
            generation.error = error instanceof Error ? error.message : 'PostHog AI failed. Try again.'
        } finally {
            clearTimeout(idleTimer)
            generation.done = true
        }
    }
}
