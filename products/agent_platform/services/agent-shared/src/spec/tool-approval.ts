/**
 * Tool-authorization chokepoint. One function resolves the approval level for any
 * spec `ToolRef`, discriminating over every `kind` with a final `assertNever`, so
 * a new tool lane is a compile error here until it's explicitly gated.
 *
 * The native intrinsic class is injected (its table lives in `agent-tools`, which
 * depends on `agent-shared`, so importing it here would cycle). MCP-sourced tools
 * aren't `ToolRef`s — they're gated separately by `effectiveToolLevel`.
 */
import type { NativeApprovalClass, ToolApprovalLevel, ToolRef } from './spec'

/** Exhaustiveness guard — unreachable at runtime; a compile error if a `ToolRef`
 *  kind is added without a branch above. */
function assertNever(x: never): never {
    throw new Error(`unhandled ToolRef kind: ${JSON.stringify(x)}`)
}

export interface ResolveToolApprovalDeps {
    /** Intrinsic approval class for a native tool id (fail-closed on unknown). */
    nativeApprovalClass: (id: string) => NativeApprovalClass
}

/**
 * Effective approval level for an in-spec tool ref. Fail closed: an author may
 * tighten (e.g. force `approve` on a read-only tool) but never loosen a tool
 * below its intrinsic class.
 */
export function resolveToolRefApprovalLevel(ref: ToolRef, deps: ResolveToolApprovalDeps): ToolApprovalLevel {
    switch (ref.kind) {
        case 'native': {
            const intrinsic = deps.nativeApprovalClass(ref.id)
            // Author may escalate (requires_approval) but not de-escalate below intrinsic.
            return intrinsic === 'approve' || ref.requires_approval ? 'approve' : 'allow'
        }
        case 'custom':
            // Custom (sandbox) tools run author code; the author's ref carries the
            // policy. Default in the schema is `requires_approval: false`, so the
            // gate is the author's explicit choice here.
            return ref.requires_approval ? 'approve' : 'allow'
        case 'client':
            // Client tools have no approval field in the spec today. Fail closed
            // rather than silently allow.
            return 'approve'
        default:
            return assertNever(ref)
    }
}
