import { CreateStoreOptions, KeaPlugin } from '../types'
import { listeners, ListenersPluginContext, sharedListeners } from './listeners'
import { getContext, setPluginContext } from '../kea/context'
import { connect } from './connect'
import { actions } from './actions'
import { defaults } from './defaults'
import { reducers } from './reducers'
import { selectors } from './selectors'
import { events } from './events'
import { runPlugins } from '../kea/plugins'
import {Action} from "redux";

export { actions } from './actions'
export { connect } from './connect'
export { defaults } from './defaults'
export { events, afterMount, beforeUnmount, propsChanged } from './events'
export { listeners, sharedListeners } from './listeners'
export { reducers } from './reducers'
export { selectors } from './selectors'
export { key } from './key'
export { props } from './props'
export { path } from './path'

export const corePlugin: KeaPlugin = {
  name: 'core',

  // assign defaults values to the logic
  defaults: () => ({
    actionCreators: {},
    actionKeys: {},
    actionTypes: {},
    actions: {},
    asyncActions: {},
    cache: {},
    connections: {},
    defaults: {},
    listeners: undefined,
    reducers: {},
    reducer: undefined,
    reducerOptions: {},
    selector: undefined,
    selectors: {},
    sharedListeners: undefined,
    values: {},
    events: {},
  }),

  events: {
    // setup defaults for listeners
    afterPlugin(): void {
      // `byAction` and `byPath` live in the engine. These getters return a snapshot.
      const listenersContext = {
        pendingPromises: new Map(),
        pendingDispatches: new Map(),
      } as ListenersPluginContext
      Object.defineProperties(listenersContext, {
        byAction: { get: () => getContext().__engine.listenersByAction(), enumerable: true },
        byPath: { get: () => getContext().__engine.listenersByPath(), enumerable: true },
      })
      setPluginContext<ListenersPluginContext>('listeners', listenersContext)
    },

    // add listeners middleware
    beforeReduxStore(options: CreateStoreOptions): void {
      options.middleware.push((store) => (next) => (action: any) => {
        const previousState = store.getState()
        const response = next(action)
        // The engine finds the listeners. They run here, so that listener chains never recurse
        // through WebAssembly frames.
        const listenerArrays = getContext().__engine.listenersFor(action)
        if (listenerArrays) {
          for (const listenerArray of listenerArrays) {
            for (const innerListener of listenerArray) {
              innerListener(action, previousState)
            }
          }
        }
        return response
      })
    },

    // support kea 2.0 style object building
    legacyBuild: (logic, input) => {
      'connect' in input && input.connect && connect(input.connect)(logic)
      runPlugins('legacyBuildAfterConnect', logic, input)
      'actions' in input && input.actions && actions(input.actions)(logic)
      'defaults' in input && input.defaults && defaults(input.defaults)(logic)
      runPlugins('legacyBuildAfterDefaults', logic, input)
      'reducers' in input && input.reducers && reducers(input.reducers)(logic)
      'selectors' in input && input.selectors && selectors(input.selectors)(logic)
      'sharedListeners' in input && sharedListeners(input.sharedListeners)(logic)
      'listeners' in input && input.listeners && listeners(input.listeners)(logic)
      'events' in input && input.events && events(input.events)(logic)
    },
  },
}
