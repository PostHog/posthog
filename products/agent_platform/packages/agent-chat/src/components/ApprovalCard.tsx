/**
 * Inline approval card — appears between turns when the runner is
 * waiting on a human gate.
 */

import type { PendingApproval } from '../types'
import { JsonView } from './JsonView'

interface ApprovalCardProps {
    approval: PendingApproval
    onApprove?: (callId: string) => void
    onDeny?: (callId: string) => void
}

export function ApprovalCard({ approval, onApprove, onDeny }: ApprovalCardProps): React.ReactElement {
    return (
        <div className="rounded-md border border-warning/40 bg-warning/5 p-3" data-slot="agent-chat-approval">
            <div className="mb-2 flex items-center gap-2 text-xs">
                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-warning" aria-hidden />
                <span className="font-medium text-foreground">Needs your OK</span>
                <code className="ml-auto truncate text-[0.6875rem] text-muted-foreground">{approval.toolId}</code>
            </div>
            <div className="mb-2">
                <JsonView value={approval.args} expandToLevel={1} />
            </div>
            <div className="flex gap-2">
                <button
                    type="button"
                    onClick={() => onApprove?.(approval.callId)}
                    className="inline-flex h-7 cursor-pointer items-center rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
                >
                    Approve
                </button>
                <button
                    type="button"
                    onClick={() => onDeny?.(approval.callId)}
                    className="inline-flex h-7 cursor-pointer items-center rounded-md border border-border bg-background px-3 text-xs font-medium transition-colors hover:bg-accent"
                >
                    Deny
                </button>
            </div>
        </div>
    )
}
