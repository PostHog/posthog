import { HogFlow } from '../../schema/hogflow'
import { CyclotronJobInvocationHogFunction } from '../../types'

// The trigger event of every transactional email run. Among emails, only transactional templates can be sensitive.
export const TRANSACTIONAL_EMAIL_EVENT = '$transactional_email'

export const hasSensitiveMessageStep = (hogFlow: Partial<Pick<HogFlow, 'actions'>> | undefined): boolean =>
    Array.isArray(hogFlow?.actions) &&
    hogFlow.actions.some(
        (action) =>
            (action?.type === 'function_email' || action?.type === 'function_push') && action.config?.sensitive === true
    )

export const isSensitiveMessage = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'state' | 'hogFunction'>
): boolean => {
    const metadata = invocation.hogFunction?.metadata
    const stepSensitive = metadata?.sensitive === true
    // A send can wait in the queue, and the template can be marked sensitive while it waits. The send API refuses
    // `sensitive: false` only for a template that is already marked, so a marked template wins here too. A key
    // without a template has a step that is always sensitive, which the send's own flag can turn off.
    if (stepSensitive && metadata?.template_uuid) {
        return true
    }
    return invocation.state?.send?.sensitive ?? stepSensitive
}
