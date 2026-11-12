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

const isTemplateMarkedSensitive = (metadata: Record<string, any> | undefined): boolean =>
    metadata?.sensitive === true && Boolean(metadata?.template_uuid)

export const isSensitiveMessage = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'state' | 'hogFunction'>
): boolean =>
    isTemplateMarkedSensitive(invocation.hogFunction?.metadata) ||
    (invocation.state?.send?.sensitive ?? invocation.hogFunction?.metadata?.sensitive === true)
