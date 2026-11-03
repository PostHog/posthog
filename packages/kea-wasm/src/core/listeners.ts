import {
  BreakPointFunction,
  BuiltLogic,
  ListenerFunction,
  ListenerFunctionWrapper,
  Logic,
  LogicBuilder,
  LogicInput,
} from '../types'
import { getContext, getPluginContext } from '../kea/context'
import { afterMount, beforeUnmount } from './events'

export const LISTENERS_BREAKPOINT = 'kea-listeners breakpoint broke'
export const isBreakpoint = (error: Error): boolean => error.message === LISTENERS_BREAKPOINT

export type ListenersPluginContext = {
  byPath: Record<string, Record<string, ListenerFunctionWrapper[]>>
  byAction: Record<string, Record<string, ListenerFunctionWrapper[]>>
  pendingPromises: Map<Promise<void>, [BuiltLogic, string]>
  pendingDispatches: Map<string, Set<Promise<void>>>
}

export function listeners<L extends Logic = Logic>(input: LogicInput<L>['listeners']): LogicBuilder<L> {
  return (logic) => {
    if (!logic.listeners) {
      logic.listeners = {}
      afterMount(() => {
        addListeners(logic)
      })(logic)
      beforeUnmount(() => {
        removeListeners(logic)

        // trigger all breakpoints
        if (logic.cache.listenerBreakpointCounter) {
          for (const key of Object.keys(logic.cache.listenerBreakpointCounter)) {
            logic.cache.listenerBreakpointCounter[key] += 1
          }
        }
      })(logic)
    }

    logic.cache.listenerBreakpointCounter ??= {}
    logic.cache.listenerLastDispatchId ??= {}

    const listeners = (typeof input === 'function' ? input(logic) : input) as Record<string, ListenerFunction>
    const { contextId } = getContext()

    for (const actionKey of Object.keys(listeners)) {
      const listenerArray: ListenerFunction[] = Array.isArray(listeners[actionKey])
        ? (listeners[actionKey] as unknown as ListenerFunction[])
        : [listeners[actionKey]]

      let key = actionKey
      if (typeof logic.actions[key] !== 'undefined') {
        key = logic.actions[key].toString()
      }

      const start = logic.listeners[key] ? logic.listeners[key].length : 0

      const listenerWrapperArray: ListenerFunctionWrapper[] = listenerArray.map(
        (listener, index): ListenerFunctionWrapper => {
          const listenerKey = `${contextId}/${key}/${start + index}`
          return (action, previousState) => {
            const breakCounter = (logic.cache.listenerBreakpointCounter[listenerKey] || 0) + 1
            logic.cache.listenerBreakpointCounter[listenerKey] = breakCounter
            logic.cache.listenerLastDispatchId[listenerKey] = action.dispatchId

            const throwIfCalled = () => {
              if (
                logic.cache.listenerBreakpointCounter[listenerKey] !== breakCounter ||
                contextId !== getContext().contextId
              ) {
                const error = new Error(LISTENERS_BREAKPOINT)
                ;(error as any).__keaDispatchId = logic.cache.listenerLastDispatchId[listenerKey]
                throw error
              }
            }

            const breakpoint = ((ms): Promise<void> | void => {
              if (typeof ms !== 'undefined') {
                return new Promise((resolve) => setTimeout(resolve, ms)).then(() => {
                  throwIfCalled()
                })
              } else {
                throwIfCalled()
              }
            }) as BreakPointFunction

            let response: any
            try {
              response = listener(action.payload, breakpoint, action, previousState)

              if (response && response.then && typeof response.then === 'function') {
                trackPendingListener(logic, actionKey, response)
                if (action.dispatchId) {
                  addDispatchListener(action.dispatchId, response)
                }
                return response
                  .catch((e: any) => {
                    if (e.message !== LISTENERS_BREAKPOINT) {
                      throw e
                    }
                  })
                  .finally(() => {
                    removeDispatchListener(action.dispatchId, response)
                  })
              }
            } catch (e: any) {
              if (e.message !== LISTENERS_BREAKPOINT) {
                throw e
              }
            }

            return response
          }
        },
      )
      if (logic.listeners[key]) {
        logic.listeners[key] = [...logic.listeners[key], ...listenerWrapperArray]
      } else {
        logic.listeners[key] = listenerWrapperArray
      }
    }
  }
}

export function sharedListeners<L extends Logic = Logic>(input: LogicInput<L>['sharedListeners']): LogicBuilder<L> {
  return (logic) => {
    logic.sharedListeners = {
      ...(logic.sharedListeners || {}),
      ...(typeof input === 'function' ? input(logic) : input),
    }
  }
}

function addListeners(logic: BuiltLogic) {
  const listeners = logic.listeners ?? {}
  const types: string[] = []
  const arrays: ListenerFunctionWrapper[][] = []
  for (const [key, listenerArray] of Object.entries(listeners)) {
    types.push(logic.actionTypes[key] ?? key)
    arrays.push(listenerArray)
  }
  getContext().__engine.listenersAdd(logic.pathString, listeners, types, arrays)
}

function removeListeners(logic: BuiltLogic) {
  const types = Object.keys(logic.listeners ?? {}).map((key) => logic.actionTypes[key] ?? key)
  getContext().__engine.listenersRemove(logic.pathString, types)
}

function trackPendingListener(logic: BuiltLogic, actionKey: string, response: Promise<void>) {
  const { pendingPromises } = getPluginContext<ListenersPluginContext>('listeners')
  pendingPromises.set(response, [logic, actionKey])
  const remove = () => {
    pendingPromises.delete(response)
  }
  response.then(remove).catch(remove)
}

function addDispatchListener(dispatchId: string, response: Promise<void>) {
  const { pendingDispatches } = getPluginContext<ListenersPluginContext>('listeners')
  const dispatches = pendingDispatches.get(dispatchId)
  if (dispatches) {
    dispatches.add(response)
  } else {
    pendingDispatches.set(dispatchId, new Set([response]))
  }
}

function removeDispatchListener(dispatchId: string, response: Promise<void>) {
  const { pendingDispatches } = getPluginContext<ListenersPluginContext>('listeners')
  const dispatches = pendingDispatches.get(dispatchId)
  if (dispatches) {
    dispatches.delete(response)
    if (dispatches.size === 0) {
      pendingDispatches.delete(dispatchId)
    }
  }
}
