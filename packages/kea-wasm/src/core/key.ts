import { KeyType, Logic, LogicBuilder } from '../types'

export function key<L extends Logic = Logic>(input: (props: L['props']) => KeyType): LogicBuilder<L> {
  return (logic) => {
    const key = input(logic.props)

    if (typeof logic.keyBuilder !== 'undefined') {
      throw new Error(`[KEA] Already defined key builder for logic "${logic.pathString}".`)
    }
    if (typeof key === 'undefined') {
      throw new Error(`[KEA] Undefined key for logic "${logic.pathString}"`)
    }
    if (Object.keys(logic.actions).length > 0) {
      throw new Error(
        `[KEA] Can not add key to logic "${logic.pathString}" after adding actions: ${Object.keys(logic.actions).join(
          ', ',
        )}`,
      )
    }

    logic.key = key
    logic.keyBuilder = input
    let isAutomaticPath = '_keaAutomaticPath' in logic.path
    logic.path = [...logic.path, logic.key]
    logic.pathString = logic.path.join('.')
    if (isAutomaticPath) {
      ;(logic.path as any)['_keaAutomaticPath'] = true
    }
  }
}
