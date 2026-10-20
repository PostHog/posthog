import { HogFlow } from '../../schema/hogflow'

export const hasSensitiveEmailStep = (hogFlow: Partial<Pick<HogFlow, 'actions'>> | undefined): boolean =>
    Array.isArray(hogFlow?.actions) &&
    hogFlow.actions.some((action) => action?.type === 'function_email' && action.config?.sensitive === true)
