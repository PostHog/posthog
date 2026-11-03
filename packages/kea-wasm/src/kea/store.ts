// The Redux maintainers have deprecated "createStore" to push everyone to use Redux Toolkit :/
// so we must import `createStore` as `legacy_createStore`
import { legacy_createStore as reduxCreateStore, applyMiddleware, compose } from 'redux'
import type { Store, StoreEnhancer } from 'redux'

import { createReduxStoreReducer, initRootReducerTree } from './reducer'
import { runPlugins } from './plugins'
import { getContext } from './context'
import { CreateStoreOptions } from '../types'
import { isPaused } from '../react/hooks'

const reduxDevToolsCompose =
  typeof window !== 'undefined' && (window as any)['__REDUX_DEVTOOLS_EXTENSION_COMPOSE__']
    ? (window as any)['__REDUX_DEVTOOLS_EXTENSION_COMPOSE__']
    : compose

const createDefaultOptions = (): CreateStoreOptions => ({
  paths: [],
  reducers: {},
  preloadedState: undefined,
  middleware: [],
  compose: reduxDevToolsCompose,
  enhancers: [],
  plugins: [],
})

export function createStore(opts = {}): Store | void {
  const context = getContext()

  if (!context) {
    console.error('[KEA] Can not create a store without a Kea context.')
    return
  }

  if (context['__store']) {
    console.error('[KEA] Already attached to a store! Exiting. Please reset the kea context before creating a store.')
    return
  }

  // clone options
  const options = { ...createDefaultOptions(), ...opts }

  // clone redux reducers
  context.reducers.redux = { ...options.reducers }

  // run pre-hooks
  runPlugins('beforeReduxStore', options)

  // combine middleware into the first enhancer
  if (options.middleware.length > 0) {
    options.enhancers = ([applyMiddleware(...options.middleware)] as StoreEnhancer[]).concat(options.enhancers)
  }

  // use a special compose function?
  const composeEnhancer: typeof compose = options.compose || compose

  // create the store creator
  const finalCreateStore = composeEnhancer(
    pauseListenersEnhancer,
    ...options.enhancers,
  )(reduxCreateStore) as typeof reduxCreateStore

  // if we are whitelisting paths
  if (options.paths && options.paths.length > 0) {
    context.reducers.whitelist = Object.fromEntries(options.paths.map((pathStart) => [pathStart, true]))
    options.paths.forEach((pathStart) => {
      initRootReducerTree(pathStart)
    })
  } else {
    initRootReducerTree('kea')
  }

  // create store
  const store = finalCreateStore(createReduxStoreReducer(), { ...options.preloadedState })
  context['__store'] = store

  // run post-hooks
  runPlugins('afterReduxStore', options, store)

  return store
}

/** Pauses Redux listeners when a logic is mounting, to avoid early re-renders from React */
export const pauseListenersEnhancer: StoreEnhancer = (createStore) => (reducer, initialState) => {
  const store = createStore(reducer, initialState)
  const storeSubscribe = store.subscribe
  store.subscribe = (observer) => {
    const pausedObserver = () => {
      if (!isPaused()) {
        observer()
      }
    }
    return storeSubscribe(pausedObserver)
  }
  return store
}
