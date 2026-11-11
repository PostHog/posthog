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

// A code send's own `sensitive` replaces the step's, so a send can relax or tighten the template it runs on.
export const isSensitiveMessage = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'state' | 'hogFunction'>
): boolean => invocation.state?.send?.sensitive ?? invocation.hogFunction?.metadata?.sensitive === true
