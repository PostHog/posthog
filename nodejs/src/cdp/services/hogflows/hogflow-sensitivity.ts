import { HogFlow } from '../../schema/hogflow'

// The trigger event of every transactional email run. Only transactional templates can be sensitive.
export const TRANSACTIONAL_EMAIL_EVENT = '$transactional_email'

export const hasSensitiveEmailStep = (hogFlow: Partial<Pick<HogFlow, 'actions'>> | undefined): boolean =>
    Array.isArray(hogFlow?.actions) &&
    hogFlow.actions.some((action) => action?.type === 'function_email' && action.config?.sensitive === true)
