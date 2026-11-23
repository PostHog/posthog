import type { ActionsActionCreateInput } from '../generated/api.js'
import { type Definition, defineKind, isDefinition } from './definition.js'
import type { EventDefinition } from './event.js'

type Step = NonNullable<ActionsActionCreateInput['steps']>[number]

export interface ActionStepInput extends Omit<Step, 'event'> {
    // An event definition, or an event name.
    event?: EventDefinition | Step['event']
}

export interface ActionInput extends Omit<ActionsActionCreateInput, 'steps'> {
    steps?: readonly ActionStepInput[]
}

export type ActionDefinition<Key extends string = string> = Definition<'action', Key, ActionsActionCreateInput>

export function action<const Key extends string>(key: Key, input: ActionInput): ActionDefinition<Key> {
    const { steps, ...fields } = input
    const body: ActionsActionCreateInput = {
        ...fields,
        ...(steps
            ? {
                  steps: steps.map(({ event, ...step }) => ({
                      ...step,
                      ...(event !== undefined ? { event: isDefinition(event) ? event.key : event } : {}),
                  })),
              }
            : {}),
    }
    return defineKind('action', key, body)
}
