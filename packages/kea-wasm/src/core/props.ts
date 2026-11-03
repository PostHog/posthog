import { Logic, LogicBuilder } from '../types'
import { shallowCompare } from '../utils'

export function props<L extends Logic = Logic>(input: L['props']): LogicBuilder<L> {
  return (logic) => {
    // set the props that haven't been initialized on build
    const newProps = { ...input, ...logic.props }
    if (!shallowCompare(logic.props, newProps)) {
      logic.lastProps = newProps
      Object.assign(logic.props, newProps)
    }
  }
}
