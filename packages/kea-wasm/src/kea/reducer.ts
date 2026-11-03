import { getContext } from './context'
import { runPlugins } from './plugins'
import { BuiltLogic, ReducerFunction } from '../types'
import type { Reducer } from 'redux'
import { ensureStackHeadroom, generatedLogicReducers } from '../engine'

export const ATTACH_REDUCER = '@KEA/ATTACH_REDUCER'
export const DETACH_REDUCER = '@KEA/DETACH_REDUCER'

const defaultState = {}

// The reducer tree, the compiled root reducers and the combined reducer live in the Rust engine.
// See crate/src/lib.rs. These functions keep the kea API and run the plugin events.

export function initRootReducerTree(pathStart: string): void {
  ensureStackHeadroom()
  getContext().__engine.initRoot(pathStart)
}

export function keaReducer(pathStart = 'scenes'): ReducerFunction {
  const engine = getContext().__engine
  initRootReducerTree(pathStart)

  return (state = defaultState, action, fullState) => {
    ensureStackHeadroom()
    return engine.reduceRoot(pathStart, state, action, fullState)
  }
}

export function attachReducer(logic: BuiltLogic): void {
  const { path, reducer } = logic
  const {
    options: { attachStrategy },
    store,
    __engine: engine,
  } = getContext()

  const pathParts = path.map((p) => p.toString())
  const generated = generatedLogicReducers.get(reducer as Function)
  ensureStackHeadroom()
  const result = generated
    ? engine.attachLogic(pathParts, reducer, generated.handle, generated.slots)
    : engine.attach(pathParts, reducer)
  if (result !== true) {
    console.error(`[KEA] Can not add reducer to "${path.join('.')}". There is something in the way:`, result)
    return
  }

  if (attachStrategy === 'dispatch' || attachStrategy === 'replace') {
    runPlugins('beforeAttach', logic)

    if (attachStrategy === 'dispatch') {
      store && store.dispatch({ type: ATTACH_REDUCER, payload: { path, reducer } })
    } else if (attachStrategy === 'replace') {
      store && store.replaceReducer(createReduxStoreReducer())
    }

    runPlugins('afterAttach', logic)
  }
}

export function detachReducer(logic: BuiltLogic): void {
  const { path } = logic

  const {
    options: { detachStrategy },
    store,
    __engine: engine,
  } = getContext()

  if (detachStrategy === 'persist') {
    return
  }

  ensureStackHeadroom()
  const detached = engine.detach(path.map((p) => p.toString()))

  if (detached) {
    if (detachStrategy === 'dispatch' || detachStrategy === 'replace') {
      runPlugins('beforeDetach', logic)

      if (detachStrategy === 'dispatch') {
        store && store.dispatch({ type: DETACH_REDUCER, payload: { path } })
      } else if (detachStrategy === 'replace') {
        store && store.replaceReducer(createReduxStoreReducer())
      }

      runPlugins('afterDetach', logic)
    }
  }
}

export function regenerateRootReducer(pathStart: string): void {
  const engine = getContext().__engine
  ensureStackHeadroom()
  engine.regenerateRoot(pathStart)
}

/** Builds a reducer from a reducer tree node, like the JavaScript kea. Runs in the engine. */
export function recursiveCreateReducer(treeNode: ReducerFunction | Record<string, any>): ReducerFunction {
  if (typeof treeNode === 'function') {
    return treeNode as ReducerFunction
  }
  const engine = new (getContext().__engine.constructor as any)()
  engine.setTree({ kea: treeNode })
  engine.regenerateRoot('kea')
  return (state, action, fullState) => {
    ensureStackHeadroom()
    return engine.reduceRoot('kea', state, action, fullState)
  }
}

// We are using our own function for the tree nodes instead of redux's combineReducers beacause this way we will not
// get the constant 'Unexpected key "1" found in previous state received by the reducer' warnings when unmounting.
// Instead we'll simply discard the keys we don't need.
export function combineKeaReducers(reducers: Record<string, ReducerFunction>): ReducerFunction {
  return function combination(state = {}, action, fullState) {
    const reducerKeys = Object.keys(reducers)
    let stateChanged = Object.keys(state).length !== reducerKeys.length
    const nextState: Record<string, any> = {}

    for (const key of reducerKeys) {
      const reducer = reducers[key]
      const previousKeyState = state[key]
      const nextKeyState = reducer(previousKeyState, action, fullState || state)
      if (typeof nextKeyState === 'undefined') {
        throw new Error(`[KEA] Reducer "${key}" returned undefined for action "${action && action.type}"`)
      }
      nextState[key] = nextKeyState
      stateChanged = stateChanged || nextKeyState !== previousKeyState
    }

    return stateChanged ? nextState : state
  }
}

export function createReduxStoreReducer(): Reducer {
  ensureStackHeadroom()
  getContext().__engine.regenerateCombined()
  return (state = defaultState, action) => getContext().reducers.combined?.(state, action, state)
}
