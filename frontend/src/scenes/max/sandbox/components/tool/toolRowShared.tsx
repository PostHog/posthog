import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { SandboxToolDebugDetails } from './SandboxToolDebugDetails'
import { resolveToolCallStatus } from './toolContentUtils'

export interface ToolRowChrome {
    isLoading: boolean
    isFailed: boolean
    wasCancelled: boolean
    errorMessage?: string
    debugDetails?: JSX.Element
}

/**
 * Derives the props every per-tool renderer forwards to `SandboxToolRow` unchanged: the resolved
 * status flags, the failure line, and the staff/dev-gated raw inspector. Keeps each renderer focused
 * on its own header/body instead of repeating this boilerplate.
 */
export function resolveToolRowChrome(props: SandboxToolRendererProps): ToolRowChrome {
    const { isLoading, isFailed, wasCancelled } = resolveToolCallStatus(
        props.message.status,
        !!props.turnCancelled,
        !!props.turnComplete
    )
    return {
        isLoading,
        isFailed,
        wasCancelled,
        errorMessage: props.message.error?.message ?? undefined,
        debugDetails: props.showRawDetails ? <SandboxToolDebugDetails message={props.message} /> : undefined,
    }
}
