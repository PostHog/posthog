import { BuiltLogic, Logic, LogicBuilder } from '../types'
import { getContext } from '../kea/context'

export function defaults<L extends Logic = Logic>(
  input:
    | ((logic: L) => (state: any, props: L['props']) => Partial<{ [T in keyof L['values']]: L['values'][T] }>)
    | ((logic: L) => Partial<{ [T in keyof L['values']]: L['values'][T] }>)
    | Partial<{ [T in keyof L['values']]: L['values'][T] }>,
): LogicBuilder<L> {
  return (logic) => {
    const defaults = typeof input === 'function' ? input(logic) : input

    if (typeof defaults === 'function') {
      logic.defaults['*'] = defaults
    } else if (typeof defaults === 'object') {
      const contextDefaults = getContextDefaults(logic)
      for (const [key, value] of Object.entries(defaults)) {
        logic.defaults[key] =
          contextDefaults && typeof contextDefaults[key] !== 'undefined' ? contextDefaults[key] : value
      }
    } else {
      throw new Error(`[KEA] Unknown defaults of type "${typeof defaults}" for logic "${logic.pathString}"`)
    }
  }
}

export function getContextDefaults(logic: BuiltLogic): Record<string, any> | void {
  let { reducerDefaults } = getContext()
  if (reducerDefaults && !('_keaAutomaticPath' in logic.path)) {
    if (getContext().options.flatDefaults) {
      if (reducerDefaults[logic.pathString]) {
        return reducerDefaults[logic.pathString]
      }
    } else {
      for (const part of logic.path) {
        reducerDefaults = reducerDefaults[part.toString()]
        if (typeof reducerDefaults !== 'object') {
          return
        }
      }
      return reducerDefaults
    }
  }
}
