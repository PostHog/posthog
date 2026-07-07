/**
 * Pick a sandbox pool impl from typed config. Single switch point so the
 * runner stays agnostic. Prod must explicitly pick `modal` (or `docker` for
 * local dev with isolation); `in-process` is **not** a valid choice at this
 * boundary, and `InProcessSandboxPool`'s constructor refuses to run unless
 * `NODE_ENV=test` — harness + per-package tests instantiate it directly
 * under vitest, which sets the env automatically. Any other call site is a
 * wiring mistake and fails fast.
 */

import { SandboxPool } from './sandbox'
import { DockerSandboxPool } from './sandbox-docker'
import { ModalSandboxPool } from './sandbox-modal'

export type SandboxBackend = 'docker' | 'modal'

export interface SandboxSelectionConfig {
    /** Required at the selector boundary; the config schema accepts undefined
     *  so tests that don't construct a sandbox pool can still parse config. */
    backend: SandboxBackend | undefined
    /** Canonical `posthog-agent-sandbox-host` reference (pinned by SHA in prod).
     *  Applies to both backends unless a per-backend image override is set. */
    sandboxHostImage?: string
    /** Backend-specific Docker image override. Takes precedence over sandboxHostImage. */
    sandboxDockerImage?: string
    /** Backend-specific Modal image override. Takes precedence over sandboxHostImage. */
    sandboxModalImage?: string
    /** Modal app name (optional — Modal SDK has a default). */
    modalAppName?: string
    /** Modal region pin (e.g. `us-east`, `eu-west`). */
    modalRegion?: string
    /** CIDRs the Modal sandbox may reach outbound. Empty → no egress (block_network). */
    sandboxOutboundCidrAllowlist?: string[]
}

export function selectSandboxPool(config: SandboxSelectionConfig): SandboxPool {
    if (!config.backend) {
        throw new Error(
            "SANDBOX_BACKEND must be 'modal' (prod) or 'docker' (local). In-process sandbox is intentionally not selectable here — tests instantiate InProcessSandboxPool directly."
        )
    }
    const resolveImage = (backendSpecific: string | undefined): string | undefined =>
        backendSpecific ?? config.sandboxHostImage
    switch (config.backend) {
        case 'docker':
            return new DockerSandboxPool({ image: resolveImage(config.sandboxDockerImage) })
        case 'modal':
            // MODAL_TOKEN_ID + MODAL_TOKEN_SECRET are read directly from env
            // by the Modal SDK — an external library we don't gate.
            return new ModalSandboxPool({
                appName: config.modalAppName,
                image: resolveImage(config.sandboxModalImage),
                region: config.modalRegion,
                outboundCidrAllowlist: config.sandboxOutboundCidrAllowlist,
            })
    }
}
