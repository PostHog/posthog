import type { AlertsAlertCreateInput } from '../generated/api.js'
import { type Definition, defineKind, type RefTo } from './definition.js'

export interface AlertInput extends Omit<AlertsAlertCreateInput, 'insight'> {
    insight: RefTo<'insight'>
}

export type AlertDefinition<Key extends string = string> = Definition<'alert', Key, AlertInput>

export function alert<const Key extends string>(key: Key, body: AlertInput): AlertDefinition<Key> {
    return defineKind('alert', key, body)
}
