import { EventDefinitions, Logic, LogicBuilder } from '../types'

export function events<L extends Logic = Logic>(
  input: EventDefinitions<L> | ((logic: L) => EventDefinitions<L>),
): LogicBuilder<L> {
  return (logic) => {
    const events = typeof input === 'function' ? input(logic) : input

    for (const key of Object.keys(events) as (keyof typeof events)[]) {
      const event = events[key]
      const newEvent = Array.isArray(event)
        ? (props: any, oldProps: any) => event.forEach((e: any) => e(props, oldProps))
        : event

      if (logic.events[key]) {
        const oldEvent = logic.events[key]
        logic.events[key] = ((props: any, oldProps: any) => {
          oldEvent?.(props, oldProps)
          newEvent?.(props, oldProps)
        }) as any
      } else if (newEvent) {
        logic.events[key] = newEvent as any
      }
    }
  }
}

export function afterMount<L extends Logic = Logic>(input: (logic: L) => void): LogicBuilder<L> {
  return events((logic) => ({ afterMount: () => input(logic) }))
}

export function beforeUnmount<L extends Logic = Logic>(input: (logic: L) => void): LogicBuilder<L> {
  return events((logic) => ({ beforeUnmount: () => input(logic) }))
}

export function propsChanged<L extends Logic = Logic>(
  input: (logic: L, oldProps: L['props']) => void,
): LogicBuilder<L> {
  return events((logic) => ({ propsChanged: (props, oldProps) => input(logic, oldProps) }))
}
