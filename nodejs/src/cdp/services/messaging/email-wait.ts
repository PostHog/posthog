import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFunction } from '../../types'
import { workflowStepDispatchKeyFromInvocation } from '../../utils/workflow-step-dispatch-key'

// Kept in the job's queue metadata so that it survives every reschedule of one send. It is keyed by the send,
// because a flow on the email queue carries its queue metadata from one step to the next.
export type EmailWait = { sendKey: string; firstDueAt: string; teamCapped: boolean }

function emailSendKey(invocation: CyclotronJobInvocationHogFunction): string {
    return workflowStepDispatchKeyFromInvocation(invocation) ?? invocation.id
}

export function readEmailWait(invocation: CyclotronJobInvocationHogFunction): EmailWait | undefined {
    const emailWait: EmailWait | undefined = invocation.queueMetadata?.emailWait
    return emailWait?.sendKey === emailSendKey(invocation) ? emailWait : undefined
}

export function queueMetadataWithEmailWait(
    invocation: CyclotronJobInvocationHogFunction,
    delay: { teamCapped: boolean }
): Record<string, any> {
    const current = readEmailWait(invocation)
    const emailWait: EmailWait = {
        sendKey: emailSendKey(invocation),
        firstDueAt: current?.firstDueAt ?? (invocation.queueDueAt ?? DateTime.utc()).toISO()!,
        teamCapped: current?.teamCapped === true || delay.teamCapped,
    }
    return { ...invocation.queueMetadata, emailWait }
}
