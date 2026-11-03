/**
  Logic builder:

  reducers({
    duckId: [10, {
      [actions.setDuckId]: (_, { duckId }) => duckId
    }]
  })

  This builder:
  - sets a default for the value if not already set
  - for each key, adds to the logic a reducer, a selector and a value
*/
import { Logic, LogicBuilder, PathType, ReducerDefinitions } from '../types'
import type { AnyAction } from 'redux'
import {
  ensureStackHeadroom,
  generatedKeyReducers,
  generatedLogicReducers,
  logicHandles,
  mappingHandles,
  slotOf,
  slotsOf,
} from '../engine'
import { getStoreState } from '../kea/context'
import { createSelector } from 'reselect'
import { getContextDefaults } from './defaults'
import { addSelectorAndValue } from './selectors'

export function rootReducer<L extends Logic = Logic>(): LogicBuilder<L> {
  return (logic) => {
    // The engine runs `combineKeaReducers(logic.reducers)` and skips reducers that can not
    // change for the dispatched action.
    const handle = logicHandles.get(logic)!
    const slots = slotsOf(logic)
    const reducer = (state: any, action: any, fullState: any) => {
      ensureStackHeadroom()
      return handle.reduce(slots, state, action, fullState)
    }
    generatedLogicReducers.set(reducer, { handle, slots })
    logic.reducer = reducer
    if (!logic.selector) {
      rootSelector()(logic)
    }
  }
}
export function rootSelector<L extends Logic = Logic>(): LogicBuilder<L> {
  return (logic) => {
    logic.selector = (state = getStoreState()) => pathSelector(logic.path, state)
  }
}

export function reducers<L extends Logic = Logic>(
  input: ReducerDefinitions<L> | ((logic: L) => ReducerDefinitions<L>),
): LogicBuilder<L> {
  return (logic) => {
    const reducers = typeof input === 'function' ? input(logic) : input

    if (!logic.reducer) {
      rootReducer()(logic)
    }
    if (!logic.selector) {
      rootSelector()(logic)
    }
    const contextDefaults = getContextDefaults(logic)

    for (const [key, object] of Object.entries(reducers)) {
      let initialValue: any
      let reducerOptions: Record<string, any> | undefined
      let reducer

      if (Array.isArray(object)) {
        // s = [ value, reducer ]
        initialValue = object[0] ?? null
        reducer = object[Math.max(1, object.length - 1)] ?? {}
        if (object.length === 3) {
          reducerOptions = object[1]
        }
      } else if (typeof object === 'object') {
        initialValue = null
        reducer = object
      } else {
        throw new Error(`[KEA] Logic "${logic.pathString}" reducer "${key}" is set to unsupported value`)
      }

      if (reducerOptions) {
        logic.reducerOptions[key] = { ...(logic.reducerOptions[key] ?? {}), ...reducerOptions }
      }

      // provide a default value if none previously provided
      if (typeof logic.defaults[key] === 'undefined') {
        if (contextDefaults && typeof contextDefaults[key] !== 'undefined') {
          logic.defaults[key] = contextDefaults[key]
        } else if (typeof logic.defaults['*'] === 'function') {
          // there is a root default selector. use it and try to get the key, fallback to initialValue
          logic.defaults[key] = (state: any, props: any) => {
            const v = logic.defaults['*'](state, props)[key]
            return typeof v === 'undefined' ? initialValue : typeof v === 'function' ? v(state, props) : v
          }
        } else {
          logic.defaults[key] = initialValue
        }
      }

      // cache the reducer keys so we can merge them when new reducer({}) calls are added on top
      logic.cache.reducers ??= {}
      logic.cache.reducers[key] ??= {}
      const mapping = logic.cache.reducers[key]
      const handle = logicHandles.get(logic)!
      let mappingHandle = mappingHandles.get(mapping)
      if (!mappingHandle) {
        mappingHandle = handle.createMapping()
        mappingHandles.set(mapping, mappingHandle)
        for (const existingKey of Object.keys(mapping)) {
          const fn = mapping[existingKey]
          mappingHandle.set(existingKey, fn ? slotOf(logic, fn) : undefined)
        }
      }
      for (const key of Object.keys(reducer ?? {})) {
        const mappingKey = logic.actions[key] ? logic.actions[key].toString() : key
        mapping[mappingKey] = reducer[key]
        mappingHandle.set(mappingKey, reducer[key] ? slotOf(logic, reducer[key]) : undefined)
      }

      if (typeof mapping['undefined'] !== 'undefined' && typeof logic.actions['undefined'] === 'undefined') {
        throw new Error(
          `[KEA] Logic "${
            logic.pathString
          }" reducer "${key}" is waiting for an action that is undefined: [${Object.keys(mapping).join(', ')}]`,
        )
      }

      // first time adding a reducer, but already a selector (having reducer + selector both is ok)
      if (!logic.reducers[key] && logic.selectors[key]) {
        throw new Error(
          `[KEA] Logic "${logic.pathString}" can't add reducer "${key}" because a selector with the same name exists.`,
        )
      }

      // create reducer for mapping
      if (Object.keys(mapping).length === 0) {
        const constantReducer = () => logic.defaults[key]
        generatedKeyReducers.set(constantReducer, { owner: handle, mapping: null })
        logic.reducers[key] = constantReducer
      } else {
        const keyReducer = (state: any, action: AnyAction, fullState: any) => {
          if (typeof state === 'undefined') {
            state = getDefaultState(logic.defaults[key], fullState, key, logic)
          }

          if (mapping[action.type]) {
            return mapping[action.type](state, action.payload, action.meta)
          } else if (logic.actionKeys[action.type] && mapping[logic.actionKeys[action.type]]) {
            return mapping[logic.actionKeys[action.type]](state, action.payload, action.meta)
          } else {
            return state
          }
        }
        // Tag the reducer before the assignment, so that the engine sees it as generated.
        generatedKeyReducers.set(keyReducer, { owner: handle, mapping: mappingHandle })
        logic.reducers[key] = keyReducer
      }

      // create selector for reducer
      if (!logic.selectors[key]) {
        addSelectorAndValue(
          logic,
          key,
          createSelector(logic.selector!, (state) => state[key]),
        )
      }
    }
  }
}

function getDefaultState(
  defaultValue: any | ((state: any, props: any) => any),
  fullState: any,
  key: any,
  logic: Logic,
) {
  if (typeof defaultValue === 'function') {
    if (fullState) {
      return defaultValue(fullState, logic.props)
    } else {
      console.error(`[KEA] Store not initialized and can't get default value of "${key}" in "${logic.pathString}"`)
      return undefined
    }
  }
  return defaultValue
}

// input: ['scenes', 'something', 'other'], state
// output: state.scenes.something.other
function pathSelector(path: PathType, state: any) {
  return [state].concat(path).reduce((v, a) => {
    if (a in v) {
      return v[a]
    }
    throw new Error(`[KEA] Can not find path "${path.join('.')}" in the store.`)
  })
}
