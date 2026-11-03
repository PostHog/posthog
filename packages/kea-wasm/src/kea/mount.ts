import { attachReducer, detachReducer } from './reducer'
import { runPlugins } from './plugins'
import { getContext } from './context'
import { BuiltLogic } from '../types'

export function mountLogic(logic: BuiltLogic, count = 1): void {
  const {
    mount: { mounted },
    __engine: engine,
  } = getContext()

  // mount this logic after all the dependencies
  const pathStrings = Object.keys(logic.connections)
    .filter((k) => k !== logic.pathString)
    .concat([logic.pathString])

  for (const pathString of pathStrings) {
    if (engine.mountIncrement(pathString, count)) {
      const connectedLogic = logic.connections[pathString]

      if (typeof connectedLogic === 'undefined') {
        throw new Error(
          `[KEA] Can not find connected logic at "${pathString}". Got "undefined" instead of the logic when trying to mount "${logic.pathString}".`,
        )
      }

      runPlugins('beforeMount', connectedLogic)
      connectedLogic.events.beforeMount?.()

      mounted[pathString] = connectedLogic

      if (connectedLogic.reducer) {
        attachReducer(connectedLogic)
      }

      runPlugins('afterMount', connectedLogic)
      connectedLogic.events.afterMount?.()
    }
  }
}

export function unmountLogic(logic: BuiltLogic): void {
  const {
    mount: { mounted },
    __engine: engine,
  } = getContext()

  // unmount in reverse order
  const pathStrings = Object.keys(logic.connections)
    .filter((k) => k !== logic.pathString)
    .concat([logic.pathString])
    .reverse()

  for (const pathString of pathStrings) {
    if (engine.mountDecrement(pathString)) {
      const connectedLogic = logic.connections[pathString]

      runPlugins('beforeUnmount', connectedLogic)
      connectedLogic.events.beforeUnmount?.()

      delete mounted[pathString]
      engine.mountDelete(pathString)

      if (connectedLogic.reducer) {
        detachReducer(connectedLogic)
      }

      runPlugins('afterUnmount', connectedLogic)
      connectedLogic.events.afterUnmount?.()

      // clear build cache
      getContext().wrapperContexts.get(connectedLogic.wrapper)?.builtLogics.delete(connectedLogic.key)
    }
  }
}
