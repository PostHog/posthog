import { HogFlow } from '../../schema/hogflow'

// The trigger event of every transactional email run. Among emails, only transactional templates can be sensitive.
export const TRANSACTIONAL_EMAIL_EVENT = '$transactional_email'

export const hasSensitiveMessageStep = (hogFlow: Partial<Pick<HogFlow, 'actions'>> | undefined): boolean =>
    Array.isArray(hogFlow?.actions) &&
    hogFlow.actions.some(
        (action) =>
            (action?.type === 'function_email' || action?.type === 'function_push') && action.config?.sensitive === true
    )
