/**
 * Unit tests for `selectSandboxPool` — covers backend dispatch + the
 * `sandboxHostImage` shared fallback (chart sets one image reference for both
 * pools). With the env→config migration these are now pure-shape assertions
 * against the typed config object; no process.env mutation.
 */

import { describe, expect, it } from 'vitest'

import { DockerSandboxPool } from './sandbox-docker'
import { ModalSandboxPool } from './sandbox-modal'
import { selectSandboxPool } from './sandbox-selector'

describe('selectSandboxPool', () => {
    it('throws a clear error when backend is undefined', () => {
        expect(() => selectSandboxPool({ backend: undefined })).toThrow(
            /SANDBOX_BACKEND must be 'modal' \(prod\) or 'docker' \(local\)/
        )
    })

    it('returns a DockerSandboxPool for backend=docker', () => {
        const pool = selectSandboxPool({ backend: 'docker' })
        expect(pool).toBeInstanceOf(DockerSandboxPool)
        expect(pool.kind).toBe('docker')
    })

    it('returns a ModalSandboxPool for backend=modal', () => {
        const pool = selectSandboxPool({ backend: 'modal' })
        expect(pool).toBeInstanceOf(ModalSandboxPool)
        expect(pool.kind).toBe('modal')
    })

    it('sandboxHostImage applies when no backend-specific override is set', () => {
        // Construction of the pools doesn't expose the image directly, so we
        // reach into each pool's stored opts via property paths the wiring
        // path touches. `as any` is acceptable for a pure-shape test.
        const sandboxHostImage = 'ghcr.io/posthog/posthog-agent-sandbox-host@sha256:abc'

        const modal = selectSandboxPool({ backend: 'modal', sandboxHostImage }) as unknown as {
            opts: { image?: string }
        }
        expect(modal.opts.image).toBe(sandboxHostImage)

        const docker = selectSandboxPool({ backend: 'docker', sandboxHostImage }) as unknown as { image: string }
        expect(docker.image).toBe(sandboxHostImage)
    })

    it('backend-specific image overrides the shared sandboxHostImage', () => {
        const modal = selectSandboxPool({
            backend: 'modal',
            sandboxHostImage: 'shared:default',
            sandboxModalImage: 'modal-only:override',
        }) as unknown as { opts: { image?: string } }
        expect(modal.opts.image).toBe('modal-only:override')

        const docker = selectSandboxPool({
            backend: 'docker',
            sandboxHostImage: 'shared:default',
            sandboxDockerImage: 'docker-only:override',
        }) as unknown as { image: string }
        expect(docker.image).toBe('docker-only:override')
    })
})
