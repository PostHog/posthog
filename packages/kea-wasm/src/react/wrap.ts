import * as React from 'react'

import { runPlugins } from '../kea/plugins'
import { AnyComponent, KeaComponent, Logic, LogicWrapper, Props } from '../types'
import { useActions, useAllValues } from './hooks'
import { getContext } from '../kea/context'

export function wrapComponent<L extends Logic = Logic>(
  Component: AnyComponent,
  wrapper: LogicWrapper<L>,
): KeaComponent {
  runPlugins('beforeWrap', wrapper, Component)

  // make this.actions work if it's a React.Component we're operating with
  injectActionsIntoClass(Component)

  const Kea: KeaComponent = function (props: Props) {
    const logic = wrapper.build(props)
    const values = useAllValues(logic)
    const actions = { ...(props.actions ?? {}), ...useActions(logic) }
    runPlugins('beforeRender', logic, props)
    return React.createElement(Component, { ...props, ...values, dispatch: getContext().store.dispatch, actions })
  }

  Kea._wrapper = wrapper
  Kea._wrappedComponent = Component

  runPlugins('afterWrap', wrapper, Component, Kea)
  return Kea
}

// inject to the component something that converts this.props.actions to this.actions
function injectActionsIntoClass(Component: AnyComponent): void {
  function isStateless(Component: AnyComponent): boolean {
    // can be various things // native arrows don't have prototypes // special property
    return typeof Component === 'function' && !(Component.prototype && Component.prototype.isReactComponent)
  }
  if (!isStateless(Component)) {
    if (!Object.getOwnPropertyDescriptor(Component.prototype, 'actions')) {
      Object.defineProperty(Component.prototype, 'actions', {
        get: function actions() {
          return this.props.actions
        },
      })
    }
  }
}
