import { getContext } from './context'
import { getBuiltLogic, getCachedBuiltLogicByKey, getCachedBuiltLogicByProps } from './build'
import { wrapComponent } from '../react/wrap'
import {
  AnyComponent,
  BuiltLogic,
  KeaComponent,
  Logic,
  LogicBuilder,
  LogicInput,
  LogicWrapper,
  Props,
  KeyType,
} from '../types'

/*

  Initializes logic and creates a wrapper that can be used to mount the logic or wrap
  it around React components.

  Logic Wrapper:

  - const logic = kea(input)

  Default behaviour (see below for explanations):

  - logic()          === logic.build()
  - logic(props)     === logic.build(props)
  - logic(Component) === logic.wrap(Component)

  Functions defined on wrappers:

  - logic.wrap(Component) # wrap around a React component
  - logic.build(props)    # build logic; optionally using props
  - logic.extend(input)   # add more input; does not alter already built logic

  Built Logic:

  - builtLogic = logic(props) = logic.build(props)

  Functions on built logic:

  - builtLogic.mount()         # mount the logic and return a function to unmount
  - builtLogic.mount(callback) # mount, run callback and unmount immediately
  - builtLogic.isMounted()     # check if logic is mounted

  Fields on built logic (core plugin):

  - builtLogic.path
  - builtLogic.pathString
  - builtLogic.props

  - builtLogic.connections
  - builtLogic.actions
  - builtLogic.defaults
  - builtLogic.reducers
  - builtLogic.reducerOptions
  - builtLogic.reducer
  - builtLogic.selector
  - builtLogic.selectors

  NB! If your input does not have a key, all the builtLogic fields can be directly
      accessed with logic.field (e.g. logic.actions). All these fields are
      automatically passed through logic.build(), so:

      logic.actions === logic().actions === logic.build().actions

      If your input has a key, you must build it with props before you can access
      its fields:

      logic(props).actions === logic.build(props).actions

  PS! Building logic is a fast operation. If we have already built the logic for the
      corresponding input and key combination (the key is derived from props), it
      will just be returned from the cache and connected with the new props.
      Feel free to call logic(props) as often as you need to.

  Constants on logic wrappers and built logic:

  - logic._isKea           # true if logic wrapper
  - builtLogic._isKeaBuild # true if built logic

*/

export function kea<L extends Logic = Logic>(
  input: LogicInput<L> | (LogicBuilder<L> | LogicInput<L>)[],
): LogicWrapper<L> {
  const wrapper: LogicWrapper<L> = function (props?: L['props']): BuiltLogic<L> | KeaComponent {
    if (typeof props === 'object' || typeof props === 'undefined') {
      return wrapper.build(props)
    }
    return wrapper.wrap(props)
  } as LogicWrapper<L>

  wrapper._isKea = true
  wrapper.inputs = (Array.isArray(input) ? input : [input]) as (LogicInput | LogicBuilder)[]

  wrapper.wrap = (Component: AnyComponent) => wrapComponent(Component, wrapper)
  wrapper.build = (props?: Props) => getBuiltLogic(wrapper, props)
  wrapper.mount = () => wrapper.build().mount()
  wrapper.unmount = () => wrapper.build().unmount()
  wrapper.isMounted = (keyOrProps?: Record<string, any> | KeyType) => !!wrapper.findMounted(keyOrProps)
  wrapper.findMounted = (keyOrProps?: Record<string, any> | KeyType) => {
    try {
      return wrapper.find(keyOrProps)
    } catch (e) {
      return null
    }
  }
  wrapper.findAllMounted = () => {
    const wrapperContext = getContext().wrapperContexts.get(wrapper)
    const found: BuiltLogic<L>[] = []
    if (!wrapperContext) {
      return found
    }
    const engine = getContext().__engine
    for (const logic of wrapperContext.builtLogics.values()) {
      if ((engine.mountCount(logic.pathString) ?? 0) > 0) {
        found.push(logic as BuiltLogic<L>)
      }
    }
    return found
  }
  wrapper.find = (keyOrProps?: Record<string, any> | KeyType) => {
    const builtLogic =
      typeof keyOrProps === 'object' || typeof keyOrProps === 'undefined'
        ? getCachedBuiltLogicByProps<L>(wrapper, keyOrProps)
        : getCachedBuiltLogicByKey<L>(wrapper, keyOrProps)
    if (builtLogic && (getContext().__engine.mountCount(builtLogic.pathString) ?? 0) > 0) {
      return builtLogic
    }
    const keyString =
      typeof keyOrProps !== 'undefined'
        ? ` with ${typeof keyOrProps === 'object' ? 'props' : 'key'} ${JSON.stringify(keyOrProps)}`
        : ''
    throw new Error(`[KEA] Can not find mounted ${builtLogic?.pathString ?? 'logic'}${keyString}`)
  }
  wrapper.extend = <ExtendLogic extends Logic = L>(
    extendedInput:
      | (LogicInput<ExtendLogic> | LogicBuilder<ExtendLogic>)[]
      | LogicInput<ExtendLogic>
      | LogicBuilder<ExtendLogic>,
  ) => {
    const wrapperContext = getContext().wrapperContexts.get(wrapper)
    if (wrapperContext) {
      throw new Error(`[KEA] Can not extend logic once it has been built.`)
    }
    if (Array.isArray(extendedInput)) {
      wrapper.inputs = wrapper.inputs.concat(extendedInput as (LogicInput<Logic> | LogicBuilder<Logic>)[])
    } else {
      wrapper.inputs.push(extendedInput as LogicInput<Logic> | LogicBuilder<Logic>)
    }
    return wrapper as unknown as LogicWrapper<ExtendLogic>
  }

  if (getContext().options.proxyFields) {
    proxyFields(wrapper)
  }

  return wrapper
}

export function proxyFieldToLogic<L extends Logic = Logic>(wrapper: LogicWrapper<L>, key: keyof L): void {
  if (!wrapper.hasOwnProperty(key)) {
    Object.defineProperty(wrapper, key, {
      get: function () {
        let logic = wrapper.findMounted()
        if (!logic && getContext().buildHeap.length > 0) {
          logic = wrapper.build()
        }
        if (logic) {
          return logic[key]
        } else {
          throw new Error(unmountedActionError(String(key), wrapper.build().pathString))
        }
      },
    })
  }
}

export function proxyFields<L extends Logic = Logic>(wrapper: LogicWrapper<L>): void {
  const reservedProxiedKeys = ['path', 'pathString', 'props'] as ['path', 'pathString', 'props']
  for (const key of reservedProxiedKeys) {
    proxyFieldToLogic(wrapper, key)
  }
  for (const key of Object.keys(getContext().plugins.logicFields)) {
    proxyFieldToLogic(wrapper, key as keyof Logic)
  }
}

export function unmountedActionError(key: string, path: string): string {
  return `[KEA] Can not access "${key}" on logic "${path}" because it is not mounted!
This can happen in several situations:
- You may need to add the "connect(otherLogic)" logic builder, or "useMountedLogic(otherLogic)" hook to make sure the logic is mounted.
- If "otherLogic" is undefined, your bundler may import and execute code in an unfavourable order. Switch to a function: "connect(() => otherLogic)" 
- It may be that the logic has already unmounted. Do you have a listener that is missing a breakpoint?`
}
