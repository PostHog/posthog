import { runPlugins } from './plugins'
import { getContext } from './context'

import { mountLogic, unmountLogic } from './mount'

import { Logic, LogicWrapper, Props, LogicInput, BuiltLogic, LogicBuilder, WrapperContext, KeyType } from '../types'
import { addConnection } from '../core/connect'
import { key, path, props } from '../core'
import { shallowCompare } from '../utils'
import { batchChanges } from '../react/hooks'
import { logicHandles, generatedKeyReducers, LogicHandle, slotOf } from '../engine'

const managedObjects = new WeakSet<object>()

/** Wraps an object in a proxy that reports every write to `sync(key, value)` or `remove(key)`. */
function managedObject(
  target: Record<string, any>,
  sync: (key: string, value: any) => void,
  remove: (key: string) => void,
): Record<string, any> {
  const proxy = new Proxy(target, {
    set(obj, prop, value) {
      const result = Reflect.set(obj, prop, value)
      if (typeof prop === 'string') {
        sync(prop, obj[prop])
      }
      return result
    },
    defineProperty(obj, prop, descriptor) {
      const result = Reflect.defineProperty(obj, prop, descriptor)
      if (typeof prop === 'string') {
        sync(prop, obj[prop])
      }
      return result
    },
    deleteProperty(obj, prop) {
      const result = Reflect.deleteProperty(obj, prop)
      if (typeof prop === 'string') {
        remove(prop)
      }
      return result
    },
  })
  managedObjects.add(proxy)
  return proxy
}

function syncReducerKey(logic: BuiltLogic, handle: LogicHandle, key: string, value: any): void {
  const generated = typeof value === 'function' ? generatedKeyReducers.get(value) : undefined
  // A value that is not a function still gets a slot. Calling it throws the same TypeError as in kea.
  const slot = slotOf(logic, value)
  if (generated && generated.owner === handle) {
    if (generated.mapping) {
      handle.setGeneratedKey(key, slot, generated.mapping)
    } else {
      handle.setConstantKey(key, slot)
    }
  } else {
    handle.setKey(key, slot)
  }
}

function syncActionKey(handle: LogicHandle, type: string, value: any): void {
  handle.setActionKey(type, value ? String(value) : undefined)
}

/** Mirrors `logic.reducers` and `logic.actionKeys` into the engine, also when a plugin replaces them. */
function manageLogicFields(logic: BuiltLogic, handle: LogicHandle): void {
  const fields: [string, (v: Record<string, any>) => void, (key: string, value: any) => void, (key: string) => void][] = [
    [
      'reducers',
      (v) => {
        handle.clearKeys()
        for (const key of Object.keys(v)) {
          syncReducerKey(logic, handle, key, v[key])
        }
      },
      (key, value) => syncReducerKey(logic, handle, key, value),
      (key) => handle.deleteKey(key),
    ],
    [
      'actionKeys',
      (v) => {
        handle.clearActionKeys()
        for (const key of Object.keys(v)) {
          syncActionKey(handle, key, v[key])
        }
      },
      (key, value) => syncActionKey(handle, key, value),
      (key) => handle.setActionKey(key, undefined),
    ],
  ]
  // Reducers without actions return `logic.defaults[key]`, so every write to it is a change.
  fields.push([
    'defaults',
    () => handle.touch(),
    () => handle.touch(),
    () => handle.touch(),
  ])
  for (const [field, resync, sync, remove] of fields) {
    let current: Record<string, any>
    const assign = (value: Record<string, any>): void => {
      if (value && typeof value === 'object') {
        current = managedObjects.has(value) ? value : managedObject(value, sync, remove)
        resync(current)
      } else {
        current = value
        resync({})
      }
    }
    assign((logic as any)[field] ?? {})
    Object.defineProperty(logic, field, {
      get: () => current,
      set: assign,
      enumerable: true,
      configurable: true,
    })
  }
}

// Converts `input` into `logic` by running all build steps in succession
function applyInputToLogic(logic: BuiltLogic, input: LogicInput | LogicBuilder) {
  runPlugins('beforeLogic', logic, input)

  // Logic builder
  if (typeof input === 'function') {
    input(logic)
  } else {
    // Legacy kea({}) object style
    'props' in input && props(input.props)(logic)
    'key' in input && typeof input.key !== 'undefined' && key(input.key)(logic)
    'path' in input && input.path && path(input.path)(logic)

    if (input.inherit) {
      for (const inheritLogic of input.inherit) {
        for (const inheritInput of inheritLogic.inputs) {
          applyInputToLogic(logic, inheritInput)
        }
      }
    }

    runPlugins('legacyBuild', logic, input)

    if (input.extend) {
      for (const innerInput of input.extend) {
        applyInputToLogic(logic, innerInput)
      }
    }
  }

  runPlugins('afterLogic', logic, input)

  return logic
}

export function getBuiltLogic<L extends Logic = Logic>(
  wrapper: LogicWrapper<L>,
  props: L['props'] | undefined,
): BuiltLogic<L> {
  // return a cached build if possible
  const wrapperContext = getWrapperContext(wrapper)
  if (wrapperContext.isBuilding) {
    throw new Error(`[KEA] Circular build detected.`)
  }

  const cachedLogic = getCachedBuiltLogicByProps(wrapper, props)
  if (cachedLogic) {
    let prevPropsClone: Props | null = null
    if (
      props &&
      (!cachedLogic.props ||
        (cachedLogic.lastProps !== props &&
          (!shallowCompare(cachedLogic.lastProps, props) ||
            !shallowCompare(cachedLogic.props, { ...cachedLogic.props, ...props }))))
    ) {
      prevPropsClone = { ...cachedLogic.props }
      Object.assign(cachedLogic.props, props)
      cachedLogic.lastProps = props
    }
    if (prevPropsClone && cachedLogic.events.propsChanged) {
      const newPropsClone = { ...cachedLogic.props }
      batchChanges(() => {
        cachedLogic.events.propsChanged?.(newPropsClone, prevPropsClone)
      })
    }
    return cachedLogic
  }

  // create a random path
  const uniqueId = ++getContext().inputCounter
  const path = [...getContext().options.defaultPath, uniqueId]
  ;(path as any)['_keaAutomaticPath'] = true
  wrapperContext.isBuilding = true

  // create a blank logic, and add the basic fields and methods
  // other core fields (actions, selectors, values, etc) are added with other plugins below.
  const logic = {
    _isKeaBuild: true,
    key: undefined,
    keyBuilder: undefined,
    path: path,
    pathString: path.join('.'),
    props: { ...props },
    lastProps: props ?? {},

    // methods
    wrapper,
    extend: (input: LogicInput) => applyInputToLogic(logic, input),
    mount: () => {
      if (wrapperContext.isBuilding) {
        throw new Error(`[KEA] Tried to mount logic "${logic.pathString}" before it finished building`)
      }
      mountLogic(logic)
      let unmounted = false
      return () => {
        if (unmounted) {
          throw new Error(`[KEA] Tried to unmount logic "${logic.pathString}" for a second time`)
        }
        unmountLogic(logic)
        unmounted = true
      }
    },
    unmount: () => unmountLogic(logic),
    isMounted: () => {
      const counter = getContext().__engine.mountCount(logic.pathString)
      return typeof counter === 'number' && counter > 0
    },
  } as any as BuiltLogic<L>

  const { buildHeap } = getContext()
  try {
    buildHeap.push(logic)

    // initialize defaults fields as requested by plugins, including core
    for (const plugin of getContext().plugins.activated) {
      if (plugin.defaults) {
        const newLogicProperties = typeof plugin.defaults === 'function' ? plugin.defaults() : plugin.defaults
        Object.assign(logic, newLogicProperties)
      }
    }

    const handle = getContext().__engine.createLogic()
    logicHandles.set(logic, handle)
    manageLogicFields(logic, handle)

    runPlugins('beforeBuild', logic, wrapper.inputs)

    // apply all the inputs and builders
    for (const input of wrapper.inputs) {
      applyInputToLogic(logic, input)
    }

    // add a connection to ourselves in the end
    logic.connections[logic.pathString] = logic

    wrapperContext.keyBuilder = logic.keyBuilder
    wrapperContext.builtLogics.set(logic.key, logic)

    runPlugins('afterBuild', logic, wrapper.inputs)
  } catch (e) {
    throw e
  } finally {
    wrapperContext.isBuilding = false
    buildHeap.pop()
  }

  // if we were building something when this got triggered, add this as a dependency for the previous logic
  if (buildHeap.length > 0) {
    if (!buildHeap[buildHeap.length - 1].connections[logic.pathString]) {
      addConnection(buildHeap[buildHeap.length - 1], logic)
    }
  }

  return logic
}

export function getCachedBuiltLogicByKey<L extends Logic = Logic>(
  wrapper: LogicWrapper<L>,
  key: KeyType | undefined,
): BuiltLogic<L> | null {
  const wrapperContext = getWrapperContext(wrapper)
  const builtLogic = wrapperContext.builtLogics.get(key)
  return builtLogic ?? null
}

export function getCachedBuiltLogicByProps<L extends Logic = Logic>(
  wrapper: LogicWrapper<L>,
  props: Props | undefined,
): BuiltLogic<L> | null {
  const wrapperContext = getWrapperContext(wrapper)
  return getCachedBuiltLogicByKey<L>(wrapper, wrapperContext?.keyBuilder?.(props ?? {}))
}

export function getWrapperContext<L extends Logic = Logic>(wrapper: LogicWrapper<L>): WrapperContext<L> {
  const { wrapperContexts } = getContext()
  let wrapperContext = wrapperContexts.get(wrapper) as WrapperContext<L> | undefined
  if (!wrapperContext) {
    wrapperContext = { keyBuilder: undefined, builtLogics: new Map(), isBuilding: false }
    wrapperContexts.set(wrapper, wrapperContext)
  }
  return wrapperContext
}
