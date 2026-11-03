import { Reducer, Store, Middleware, StoreEnhancer, compose, AnyAction } from 'redux'
import { Context as ReactContext, ComponentType, FunctionComponent } from 'react'
import { WeakMapMemoizeOptions } from 'reselect'

// universal helpers
export type AnyComponent = ComponentType | FunctionComponent
export type KeyType = string | number | boolean
export type PathType = KeyType[]
export type Selector = (state?: any, props?: any) => any
export type Props = Record<string, any> // nb! used in kea and react
export type PartialRecord<K extends keyof any, T> = Partial<Record<K, T>>

// logic base class
export interface Logic {
  // logic
  path: PathType
  pathString: string
  props: any
  lastProps: any
  key?: KeyType
  keyBuilder?: (props: any) => KeyType

  // core
  actionCreators: Record<string, any>
  actionKeys: Record<string, string>
  actionTypes: Record<string, string>
  actions: Record<string, any>
  asyncActions: Record<string, any>
  cache: Record<string, any>
  connections: { [pathString: string]: BuiltLogic }
  defaults: Record<string, any>
  reducers: Record<string, any>
  reducer?: ReducerFunction<any>
  reducerOptions: Record<string, any>
  selector?: Selector
  selectors: Record<string, Selector>
  values: Record<string, any>
  events: {
    beforeMount?: () => void
    afterMount?: () => void
    beforeUnmount?: () => void
    afterUnmount?: () => void
    propsChanged?: (props: any, oldProps: any) => void
  }

  // listeners
  listeners?: Record<string, ListenerFunctionWrapper[]>
  sharedListeners?: Record<string, ListenerFunction>

  __keaTypeGenInternalSelectorTypes: Record<string, any>
  __keaTypeGenInternalReducerActions: Record<string, any>
  __keaTypeGenInternalExtraInput: Record<string, any>
}

export interface BuiltLogicAdditions<LogicType extends Logic> {
  _isKeaBuild: boolean
  mount: () => () => void
  unmount: () => void
  isMounted: () => boolean
  extend: <ExtendLogicType extends Logic = LogicType>(
    extendedInput: LogicInput<ExtendLogicType> | LogicInput<ExtendLogicType>[],
  ) => LogicWrapper<ExtendLogicType>
  wrapper: LogicWrapper
}

export type BuiltLogic<LogicType extends Logic = Logic> = LogicType & BuiltLogicAdditions<LogicType>

export interface LogicWrapperAdditions<LogicType extends Logic> {
  _isKea: boolean
  inputs: (LogicInput | LogicBuilder)[] // store as generic
  <T extends LogicType['props'] | AnyComponent>(props: T): T extends LogicType['props']
    ? BuiltLogic<LogicType>
    : FunctionComponent
  (): BuiltLogic<LogicType>
  wrap: (Component: AnyComponent) => KeaComponent
  build: (props?: LogicType['props']) => BuiltLogic<LogicType>
  mount: () => () => void
  unmount: () => void
  /** Is a logic with the given key or props mounted? */
  isMounted: (keyOrProps?: KeyType | Record<string, any>) => boolean
  /** Find a mounted logic or return null */
  findMounted: (keyOrProps?: KeyType | Record<string, any>) => BuiltLogic<LogicType> | null
  /** Find all mounted logics */
  findAllMounted: () => BuiltLogic<LogicType>[]
  /** Find a mounted logic or throw */
  find: (keyOrProps?: KeyType | Record<string, any>) => BuiltLogic<LogicType>
  extend: <ExtendLogicType extends Logic = LogicType>(
    extendedInput: LogicInput<ExtendLogicType>,
  ) => LogicWrapper<ExtendLogicType>
}

export type LogicWrapper<LogicType extends Logic = Logic> = LogicType & LogicWrapperAdditions<LogicType>

export type LogicBuilder<L extends Logic = Logic> = (logic: BuiltLogic<L>) => void

// input helpers (using the generated logic type as input)
export type PayloadCreatorDefinition = true | ((...args: any[]) => any)
export type ActionDefinitions<LogicType extends Logic> = LogicType['actionCreators'] extends Record<string, any>
  ? Partial<{
      [K in keyof LogicType['actionCreators']]: LogicType['actionCreators'][K] extends Function
        ? ReturnType<LogicType['actionCreators'][K]>['payload']['value'] extends true
          ? true
          : (...args: Parameters<LogicType['actionCreators'][K]>) => LogicType['actionCreators'][K]['payload']
        : never
    }>
  : Record<string, PayloadCreatorDefinition>

export interface KeaReduxAction extends AnyAction {
  type: string
  payload?: any
}

export interface KeaAction {
  (...args: any[]): KeaReduxAction
  _isKeaAction: boolean
  toString(): string
}

export type ReducerActions<
  LogicType extends Logic,
  ReducerType,
> = LogicType['__keaTypeGenInternalReducerActions'] extends Record<string, never>
  ? {
      [K in keyof LogicType['actionCreators']]?: (
        state: ReducerType,
        payload: ReturnType<LogicType['actionCreators'][K]>['payload'],
      ) => ReducerType
    }
  : LogicType['__keaTypeGenInternalReducerActions'] extends Record<string, any>
  ? {
      [K in keyof LogicType['actionCreators']]?: (
        state: ReducerType,
        payload: ReturnType<LogicType['actionCreators'][K]>['payload'],
      ) => ReducerType
    } & {
      [K in keyof LogicType['__keaTypeGenInternalReducerActions']]?: (
        state: ReducerType,
        payload: ReturnType<LogicType['__keaTypeGenInternalReducerActions'][K]>['payload'],
      ) => ReducerType
    }
  : never

export type ReducerDefault<Reducer extends () => any, P extends Props> =
  | ReturnType<Reducer>
  | ((state: any, props: P) => ReturnType<Reducer>)

export type ReducerDefinitions<LogicType extends Logic> = {
  [K in keyof LogicType['reducers']]?:
    | [
        ReducerDefault<LogicType['reducers'][K], LogicType['props']>,
        Record<string, any>,
        ReducerActions<LogicType, ReturnType<LogicType['reducers'][K]>>,
      ]
    | [
        ReducerDefault<LogicType['reducers'][K], LogicType['props']>,
        ReducerActions<LogicType, ReturnType<LogicType['reducers'][K]>>,
      ]
    | [ReducerDefault<LogicType['reducers'][K], LogicType['props']>]
    | ReducerActions<LogicType, ReturnType<LogicType['reducers'][K]>>
}

export type ReducerFunction<S = any> = (state: S, action: KeaReduxAction, fullState: any) => S

export type SelectorTuple =
  | []
  | [Selector]
  | [Selector, Selector]
  | [Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector, Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector]
  | [Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector, Selector]
  | [
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
    ]
  | [
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
    ]
  | [
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
    ]
  | [
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
    ]
  | [
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
      Selector,
    ]

export type SelectorDefinition<Selectors, PropSelectors, SelectorFunction extends any> =
  | [(s: Selectors, p: PropSelectors) => SelectorTuple, SelectorFunction]
  | [(s: Selectors, p: PropSelectors) => SelectorTuple, SelectorFunction, WeakMapMemoizeOptions]

export type LogicPropSelectors<LogicType extends Logic> = {
  [PK in keyof LogicType['props']]: () => LogicType['props'][PK]
}

export type SelectorDefinitions<LogicType extends Logic> =
  | {
      [K in keyof LogicType['__keaTypeGenInternalSelectorTypes']]?: SelectorDefinition<
        LogicType['selectors'],
        LogicPropSelectors<LogicType>,
        LogicType['__keaTypeGenInternalSelectorTypes'][K]
      >
    }
  | {
      [key: string]: SelectorDefinition<LogicType['selectors'], LogicPropSelectors<LogicType>, any>
    }

export type BreakPointFunction = (() => void) & ((ms: number) => Promise<void>)

export type ListenerDefinitionsForRecord<A extends Record<string, (...args: any) => any>> = {
  [K in keyof A]?: ListenerFunction<ReturnType<A[K]>> | ListenerFunction<ReturnType<A[K]>>[]
}

export type ListenerDefinitions<LogicType extends Logic> =
  LogicType['__keaTypeGenInternalReducerActions'] extends Record<string, never>
    ? ListenerDefinitionsForRecord<LogicType['actionCreators']>
    : LogicType['__keaTypeGenInternalReducerActions'] extends Record<string, any>
    ? ListenerDefinitionsForRecord<LogicType['actionCreators']> &
        ListenerDefinitionsForRecord<LogicType['__keaTypeGenInternalReducerActions']>
    : never

export type EventDefinitions<LogicType extends Logic> = {
  beforeMount?: (() => void) | (() => void)[]
  afterMount?: (() => void) | (() => void)[]
  beforeUnmount?: (() => void) | (() => void)[]
  afterUnmount?: (() => void) | (() => void)[]
  propsChanged?:
    | ((props: Logic['props'], oldProps: Logic['props']) => void)
    | ((props: Logic['props'], oldProps: Logic['props']) => void)[]
}

export type ListenerFunction<A extends AnyAction = any> = (
  payload: A['payload'],
  breakpoint: BreakPointFunction,
  action: A,
  previousState: any,
) => void | Promise<void>

export type ListenerFunctionWrapper = (action: any, previousState: any) => void

export type SharedListenerDefinitions = Record<string, ListenerFunction>

type WindowValuesDefinitions<LogicType extends Logic> = Record<string, (window: Window) => any>

type LoaderFunctions<LogicType extends Logic, ReducerReturnType> = {
  [K in keyof LogicType['actionCreators']]?: (
    payload: ReturnType<LogicType['actionCreators'][K]>['payload'],
    breakpoint: BreakPointFunction,
    action: ReturnType<LogicType['actionCreators'][K]>,
  ) => ReducerReturnType | Promise<ReducerReturnType>
}

type LoaderDefinitions<LogicType extends Logic> = {
  [K in keyof LogicType['reducers']]?:
    | (
        | LoaderFunctions<LogicType, ReturnType<LogicType['reducers'][K]>>
        | {
            __default: ReturnType<LogicType['reducers'][K]>
          }
      )
    | [ReturnType<LogicType['reducers'][K]>, LoaderFunctions<LogicType, ReturnType<LogicType['reducers'][K]>>]
}

export type ConnectDefinitions =
  | BuiltLogic
  | LogicWrapper
  | (BuiltLogic | LogicWrapper)[]
  | {
      logic?: (BuiltLogic | LogicWrapper)[]
      values?: any[]
      actions?: any[]
    }

export type LogicInput<LogicType extends Logic = Logic> = {
  inherit?: LogicWrapper[]
  extend?: LogicInput[]
  key?: (props: LogicType['props']) => KeyType
  path?: PathType | ((key: KeyType) => PathType)
  connect?: ConnectDefinitions | ((props: LogicType['props']) => ConnectDefinitions)
  actions?: ActionDefinitions<LogicType> | ((logic: LogicType) => ActionDefinitions<LogicType>)
  reducers?: ReducerDefinitions<LogicType> | ((logic: LogicType) => ReducerDefinitions<LogicType>)
  selectors?: SelectorDefinitions<LogicType> | ((logic: LogicType) => SelectorDefinitions<LogicType>)
  listeners?: ListenerDefinitions<LogicType> | ((logic: LogicType) => ListenerDefinitions<LogicType>)
  sharedListeners?: SharedListenerDefinitions | ((logic: LogicType) => SharedListenerDefinitions)
  events?: EventDefinitions<LogicType> | ((logic: LogicType) => EventDefinitions<LogicType>)
  defaults?:
    | ((logic: LogicType) => (state: any, props: LogicType['props']) => Record<string, any>)
    | ((logic: LogicType) => Record<string, any>)
    | Record<string, any>

  // plugins
  loaders?: LoaderDefinitions<LogicType> | ((logic: LogicType) => LoaderDefinitions<LogicType>)
  windowValues?: WindowValuesDefinitions<LogicType> | ((logic: LogicType) => WindowValuesDefinitions<LogicType>)
  urlToAction?: (logic: LogicType) => Record<
    string,
    (
      params: Record<string, string | undefined>,
      searchParams: Record<string, any>,
      hashParams: Record<string, any>,
      payload: {
        method: 'PUSH' | 'REPLACE' | 'POP'
        pathname: string
        search: string
        searchParams: Record<string, any>
        hash: string
        hashParams: Record<string, any>
        url: string
        initial?: boolean
      },
      previousLocation: {
        method: 'PUSH' | 'REPLACE' | 'POP' | null
        pathname: string
        search: string
        searchParams: Record<string, any>
        hash: string
        hashParams: Record<string, any>
        url: string
      },
    ) => any
  >
  actionToUrl?: (logic: LogicType) => {
    [K in keyof LogicType['actionCreators']]?: (
      payload: Record<string, any>,
    ) =>
      | void
      | string
      | [string]
      | [string, string | Record<string, any> | undefined]
      | [string, string | Record<string, any> | undefined, string | Record<string, any> | undefined]
      | [
          string,
          string | Record<string, any> | undefined,
          string | Record<string, any> | undefined,
          { replace?: boolean },
        ]
  }

  [key: string]: unknown
} & LogicType['__keaTypeGenInternalExtraInput']

/**
  MakeLogicType:
  - create a close-enough approximation of the logic's types if passed three interfaces:

  MakeLogicType<Values, Actions, Props>
  - Values = { valueKey: type }
  - Actions = { actionKey: (id) => void }   // <- this works
  - Actions = { actionKey: (id) => { id } } // <- adds type completion in reducers
  - Props = { id: 3 }
*/
export interface MakeLogicType<
  Values extends Record<string, any> = Record<string, unknown>,
  Actions = Record<string, AnyFunction>,
  LogicProps = Props,
  Meta extends KeaLogicTypeInput = {},
> extends Logic {
  actionCreators: {
    [ActionKey in keyof Actions]: Actions[ActionKey] extends AnyFunction
      ? ActionCreatorForPayloadBuilder<Actions[ActionKey]>
      : never
  }
  actionKeys: Record<string, string>
  actionTypes: {
    [ActionKey in keyof Actions]: string
  }
  actions: {
    [ActionKey in keyof Actions]: Actions[ActionKey] extends AnyFunction
      ? ActionForPayloadBuilder<Actions[ActionKey]>
      : never
  }
  asyncActions: {
    [ActionKey in keyof Actions]: Actions[ActionKey] extends AnyFunction
      ? AsyncActionForPayloadBuilder<Actions[ActionKey]>
      : never
  }
  defaults: Values
  props: LogicProps
  reducer: ReducerFunction<Values>
  reducers: {
    [Value in keyof Values]: ReducerFunction<Values[Value]>
  }
  key: Meta['key'] extends KeyType ? Meta['key'] : KeyType | undefined
  selector: (state: any, props?: LogicProps) => Values
  selectors: {
    [Value in keyof Values]: (state: any, props?: LogicProps) => Values[Value]
  }
  sharedListeners: Meta['sharedListeners'] extends Record<string, ListenerFunction>
    ? Meta['sharedListeners']
    : Record<string, ListenerFunction> | undefined
  values: Values

  __keaTypeGenInternalSelectorTypes: Meta['__keaTypeGenInternalSelectorTypes'] extends Record<string, any>
    ? Meta['__keaTypeGenInternalSelectorTypes']
    : {
        [K in keyof Values]: (...args: any) => Values[K]
      }
  __keaTypeGenInternalReducerActions: Meta['__keaTypeGenInternalReducerActions'] extends Record<string, any>
    ? Meta['__keaTypeGenInternalReducerActions']
    : Record<string, any>
  __keaTypeGenInternalExtraInput: Meta['__keaTypeGenInternalExtraInput'] extends Record<string, any>
    ? Meta['__keaTypeGenInternalExtraInput']
    : Record<string, any>
}

export interface KeaLogicTypeInput {
  values?: Record<string, unknown>
  actions?: Record<string, AnyFunction>
  props?: Props
  key?: KeyType
  sharedListeners?: Record<string, ListenerFunction>

  __keaTypeGenInternalSelectorTypes?: Record<string, any>
  __keaTypeGenInternalReducerActions?: Record<string, any>
  __keaTypeGenInternalExtraInput?: Record<string, any>
}

/** Create a logicType for a logic from minimal input. Used in typegen inline mode. */
export interface KeaLogicType<Input extends KeaLogicTypeInput> extends Logic {
  actionCreators: {
    [ActionKey in keyof Input['actions']]: Input['actions'][ActionKey] extends AnyFunction
      ? ActionCreatorForPayloadBuilder<Input['actions'][ActionKey]>
      : never
  }
  actionKeys: Record<string, string>
  actionTypes: {
    [ActionKey in keyof Input['actions']]: string
  }
  actions: {
    [ActionKey in keyof Input['actions']]: Input['actions'][ActionKey] extends AnyFunction
      ? ActionForPayloadBuilder<Input['actions'][ActionKey]>
      : never
  }
  defaults: Input['values'] extends Record<string, unknown> ? Input['values'] : Record<string, unknown>
  props: Input['props']
  reducer: ReducerFunction<Input['values']>
  reducers: {
    [Value in keyof Input['values']]: ReducerFunction<Input['values'][Value]>
  }
  key: Input['key'] extends KeyType ? Input['key'] : KeyType | undefined
  selector: (state: any, props?: Input['props']) => Input['values']
  selectors: {
    [Value in keyof Input['values']]: (state: any, props?: Input['props']) => Input['values'][Value]
  }
  sharedListeners: Input['sharedListeners'] extends Record<string, ListenerFunction>
    ? Input['sharedListeners']
    : Record<string, ListenerFunction> | undefined
  values: Input['values'] extends Record<string, unknown> ? Input['values'] : Record<string, unknown>

  __keaTypeGenInternalSelectorTypes: Input['__keaTypeGenInternalSelectorTypes'] extends Record<string, any>
    ? Input['__keaTypeGenInternalSelectorTypes']
    : Record<string, any>
  __keaTypeGenInternalReducerActions: Input['__keaTypeGenInternalReducerActions'] extends Record<string, any>
    ? Input['__keaTypeGenInternalReducerActions']
    : Record<string, any>
  __keaTypeGenInternalExtraInput: Input['__keaTypeGenInternalExtraInput'] extends Record<string, any>
    ? Input['__keaTypeGenInternalExtraInput']
    : Record<string, any>
}

export type AnyFunction = (...args: any) => any

export type ActionCreatorForPayloadBuilder<B extends AnyFunction> = (...args: Parameters<B>) => {
  type: string
  payload: ReturnType<B>
}

export type ActionForPayloadBuilder<B extends AnyFunction> = (...args: Parameters<B>) => void
export type AsyncActionForPayloadBuilder<B extends AnyFunction> = (...args: Parameters<B>) => Promise<any>

// kea setup stuff

export interface CreateStoreOptions {
  paths: string[]
  reducers: Record<string, Reducer>
  preloadedState: Record<string, any> | undefined
  middleware: Middleware[]
  compose: typeof compose
  enhancers: StoreEnhancer[]
  plugins: KeaPlugin[]
}

export interface InternalContextOptions {
  debug: boolean
  proxyFields: boolean
  flatDefaults: boolean
  attachStrategy: 'dispatch' | 'replace'
  detachStrategy: 'dispatch' | 'replace' | 'persist'
  defaultPath: string[]
  disableAsyncActions: boolean
  // ...otherOptions
}

export interface ContextOptions extends Partial<InternalContextOptions> {
  plugins?: KeaPlugin[]
  createStore?: boolean | Partial<CreateStoreOptions>
  defaults?: Record<string, any>
}

export interface KeaComponent extends FunctionComponent {
  _wrapper: LogicWrapper
  _wrappedComponent: AnyComponent
}

export interface PluginEvents {
  /** Run after creating a new context, before plugins are activated and the store is created */
  afterOpenContext?: (context: Context, options: ContextOptions) => void
  /** Run after this plugin has been activated */
  afterPlugin?: () => void
  /** Run before the redux store creation begins. Use it to add options (middleware, etc) to the store creator. */
  beforeReduxStore?: (options: CreateStoreOptions) => void
  /** Run after the redux store is created. */
  afterReduxStore?: (options: CreateStoreOptions, store: Store) => void
  /** Run before we start doing anything */
  beforeKea?: (input: LogicInput | LogicBuilder) => void
  /** before the steps to build the logic (gets an array of inputs from kea(input).extend(input)) */
  beforeBuild?: (logic: BuiltLogic, inputs: (LogicInput | LogicBuilder)[]) => void
  /** before the steps to convert input into logic (also run once per .extend()) */
  beforeLogic?: (logic: BuiltLogic, input: LogicInput | LogicBuilder) => void
  /** after the steps to convert input into logic (also run once per .extend()) */
  afterLogic?: (logic: BuiltLogic, input: LogicInput | LogicBuilder) => void
  /** called when building a logic with legeacy LogicInput objects, called after connect: {} runs in code */
  legacyBuild?: (logic: BuiltLogic, input: LogicInput) => void
  /** called when building a logic with legeacy LogicInput objects, called after defaults are built in core */
  legacyBuildAfterConnect?: (logic: BuiltLogic, input: LogicInput) => void
  /** called when building a logic with legeacy LogicInput objects, called after the legacy core plugin runs */
  legacyBuildAfterDefaults?: (logic: BuiltLogic, input: LogicInput) => void
  /** after the steps to build the logic */
  afterBuild?: (logic: BuiltLogic, inputs: (LogicInput | LogicBuilder)[]) => void
  /** Run before a logic store is mounted in React */
  beforeMount?: (logic: BuiltLogic) => void
  /** Run after a logic store is mounted in React */
  afterMount?: (logic: BuiltLogic) => void
  /** Run before a reducer is attached to Redux */
  beforeAttach?: (logic: BuiltLogic) => void
  /** Run after a reducer is attached to Redux */
  afterAttach?: (logic: BuiltLogic) => void
  /** Run before a logic is unmounted */
  beforeUnmount?: (logic: BuiltLogic) => void
  /** Run after a logic is unmounted */
  afterUnmount?: (logic: BuiltLogic) => void
  /** Run before a reducer is detached frm Redux */
  beforeDetach?: (logic: BuiltLogic) => void
  /** Run after a reducer is detached frm Redux */
  afterDetach?: (logic: BuiltLogic) => void
  /** Run before wrapping a React component */
  beforeWrap?: (wrapper: LogicWrapper, Klass: AnyComponent) => void
  /** Run after wrapping a React component */
  afterWrap?: (wrapper: LogicWrapper, Klass: AnyComponent, Kea: KeaComponent) => void
  /** Run after mounting and before rendering the component in React's scope (you can use hooks here) */
  beforeRender?: (logic: BuiltLogic, props: Props) => void
  /** Run when we are removing kea from the system, e.g. when cleaning up after tests */
  beforeCloseContext?: (context: Context) => void
}

export type PluginEventArrays = {
  [K in keyof PluginEvents]: PluginEvents[K][]
}

export interface KeaPlugin {
  /** Required: name of the plugin */
  name: string
  /** Default values ...applied on top of built logic */
  defaults?: () => Record<string, any>
  /** Hook into various lifecycle events */
  events?: PluginEvents
}

export interface WrapperContext<L extends Logic = Logic> {
  isBuilding: boolean
  keyBuilder: L['keyBuilder']
  builtLogics: Map<KeyType | undefined, BuiltLogic<L>>
}

export interface Context {
  __engine: import('./engine').Engine
  contextId: string

  plugins: {
    activated: KeaPlugin[]
    events: PluginEventArrays
    logicFields: Record<string, string>
    contexts: Record<string, Record<string, any>>
  }

  inputCounter: number
  reducerDefaults: Record<string, any> | undefined
  wrapperContexts: WeakMap<LogicWrapper, WrapperContext>
  buildHeap: Logic[]

  mount: {
    counter: Record<string, number>
    mounted: Record<string, BuiltLogic>
  }

  react: {
    contexts: WeakMap<LogicWrapper, ReactContext<BuiltLogic | undefined>>
  }

  reducers: {
    tree: any
    roots: any
    redux: any
    whitelist: false | Record<string, boolean>
    combined: ReducerFunction | undefined
  }

  // getter that always returns something
  store: Store
  // the created store if present
  __store: Store | undefined

  options: InternalContextOptions
}
