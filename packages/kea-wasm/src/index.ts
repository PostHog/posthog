import { setGlobalDevModeChecks } from 'reselect'
export * from './types'
export * from './utils'
export * from './core'

import { resetContext } from './kea/context'

export { kea } from './kea/kea'

export {
  useValues,
  useAllValues,
  useActions,
  useAsyncActions,
  useMountedLogic,
  useSelector,
  batchChanges,
} from './react/hooks'
export { BindLogic } from './react/bind'
export { Provider } from './react/provider'

export { resetContext, openContext, closeContext, getContext, getPluginContext, setPluginContext } from './kea/context'
export { createStore } from './kea/store'
export { keaReducer } from './kea/reducer'
export { activatePlugin } from './kea/plugins'

export { createActionCreator } from './core/actions'
export { addConnection } from './core/connect'
export { isBreakpoint } from './core/listeners'

// Must do this to make TSD happy, as otherwise rollup+dts produces an invalid .d.ts file
import { ATTACH_REDUCER as A, DETACH_REDUCER as D } from './kea/reducer'

export const ATTACH_REDUCER = A as '@KEA/ATTACH_REDUCER'
export const DETACH_REDUCER = D as '@KEA/DETACH_REDUCER'

// without this we throw warnings at selectors with just one input that return the same value (aka aliases)
setGlobalDevModeChecks({ identityFunctionCheck: 'never' })

// this will create a default context
resetContext({}, true)

// kea-wasm only: engine counters for benchmarks. Not part of the kea API.
export { engineStats as __keaWasmEngineStats, resetEngineStats as __keaWasmResetEngineStats } from './engine'
