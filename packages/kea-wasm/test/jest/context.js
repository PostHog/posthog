import { kea } from '../../src'
import { activatePlugin, getContext, openContext, closeContext, resetContext } from '../../src'

describe('context', () => {
  beforeEach(() => {
    closeContext()
  })

  test('getting and setting works', () => {
    expect(getContext()).not.toBeDefined()

    openContext({ createStore: false })

    expect(getContext()).toBeDefined()

    expect(getContext()).toMatchObject({
      plugins: {
        activated: [expect.objectContaining({ name: 'core' })],
      },

      mount: {
        counter: {},
        mounted: {},
      },

      reducers: {
        tree: {},
        roots: {},
        combined: undefined,
      },

      store: undefined,

      options: {
        debug: false,
        proxyFields: true,
        flatDefaults: false,
        attachStrategy: 'dispatch',
        detachStrategy: 'dispatch',
      },
    })

    closeContext()

    expect(getContext()).not.toBeDefined()
  })

  test('context works with plugins', () => {
    expect(getContext()).not.toBeDefined()

    openContext()

    expect(getContext()).toBeDefined()

    const { plugins } = getContext()

    const testPlugin = {
      name: 'test',

      defaults: () => ({
        ranNewBuildStep: false,
      }),

      events: {
        legacyBuild(logic, input) {
          logic.ranNewBuildStep = true
        },
      },
    }

    expect(getContext()).toMatchObject({
      plugins: {
        activated: [{ name: 'core' }],
      },
    })

    activatePlugin(testPlugin)

    expect(getContext()).toMatchObject({
      plugins: {
        activated: [{ name: 'core' }, { name: 'test' }],
      },
    })

    // const logic = kea({ options:{lazy:true}})
    const logic = kea({})
    logic.mount()

    expect(logic.ranNewBuildStep).toEqual(true)

    closeContext()
    expect(getContext()).not.toBeDefined()

    openContext({ plugins: [testPlugin] })

    expect(getContext()).toBeDefined()
    expect(getContext()).toMatchObject({
      plugins: {
        activated: [expect.objectContaining({ name: 'core' }), expect.objectContaining({ name: 'test' })],
      },
    })
  })

  test('wrapperContexts work as expected', () => {
    resetContext()
    const { wrapperContexts } = getContext()

    const logic = kea({ path: ['kea', 'misc', 'blue'] })
    expect(wrapperContexts.get(logic)).not.toBeDefined()
    const builtLogic = logic.build()
    expect(wrapperContexts.get(logic)).toBeDefined()
    expect(wrapperContexts.get(logic)).toEqual({
      keyBuilder: undefined,
      isBuilding: false,
      builtLogics: new Map([[undefined, builtLogic]]),
    })

    const dynamicLogic = kea({
      key: (props) => props.id,
      path: (key) => ['kea', 'misc', 'green', key],
    })
    const builtDynamicLogic = dynamicLogic({ id: 12 })

    expect(wrapperContexts.get(dynamicLogic)).toEqual({
      keyBuilder: expect.any(Function),
      isBuilding: false,
      builtLogics: new Map([[12, builtDynamicLogic]]),
    })
    expect(wrapperContexts.get(dynamicLogic).keyBuilder({ id: 123 })).toEqual(123)
  })

  describe('defaultPath', () => {
    test('defaultPath work as expected', () => {
      openContext({
        defaultPath: ['kea', 'inline'],
      })

      kea({
        reducers: {
          hi: ['true', {}],
        },
      }).mount()

      expect(getContext().store.getState()).toEqual({
        kea: {
          inline: {
            1: {
              hi: 'true',
            },
          },
        },
      })
    })
  })

  test('nested context defaults work', () => {
    const { store } = resetContext({
      defaults: {
        scenes: { testy: { key: 'value', name: 'alfred', thisIs: 'missing' } },
      },
    })

    expect(store.getState()).toEqual({
      kea: {},
    })

    const logic = kea({
      path: () => ['scenes', 'testy'],
      reducers: () => ({
        key: ['noValue', {}],
        name: ['batman', {}],
      }),
    })

    expect(store.getState()).toEqual({
      kea: {},
    })

    logic.mount()

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { testy: { key: 'value', name: 'alfred' } },
    })

    const logic2 = kea({
      path: () => ['scenes', 'noDefaults'],
      reducers: () => ({
        key: ['noValue', {}],
        name: ['batman', {}],
      }),
    })

    logic2.mount()

    expect(store.getState()).toEqual({
      kea: {},
      scenes: {
        testy: { key: 'value', name: 'alfred' },
        noDefaults: { key: 'noValue', name: 'batman' },
      },
    })
  })

  test('flat context defaults work', () => {
    const { store } = resetContext({
      defaults: {
        'scenes.testy': { key: 'value', name: 'alfred', thisIs: 'missing' },
      },
      flatDefaults: true,
    })

    expect(store.getState()).toEqual({
      kea: {},
    })

    const logic = kea({
      path: () => ['scenes', 'testy'],
      reducers: () => ({
        key: ['noValue', {}],
        name: ['batman', {}],
      }),
    })

    expect(store.getState()).toEqual({
      kea: {},
    })

    logic.mount()

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { testy: { key: 'value', name: 'alfred' } },
    })

    const logic2 = kea({
      path: () => ['scenes', 'noDefaults'],
      reducers: () => ({
        key: ['noValue', {}],
        name: ['batman', {}],
      }),
    })

    logic2.mount()

    expect(store.getState()).toEqual({
      kea: {},
      scenes: {
        testy: { key: 'value', name: 'alfred' },
        noDefaults: { key: 'noValue', name: 'batman' },
      },
    })
  })

  test('context defaults work with defaults', () => {
    const { store } = resetContext({
      defaults: {
        'scenes.testy': { key: 'value', name: 'alfred', thisIs: 'missing' },
      },
      flatDefaults: true,
    })

    const logic = kea({
      path: ['scenes', 'testy'],
      defaults: {
        key: 'noValue',
        name: 'batman',
      },
      reducers: {
        key: {},
        name: {},
      },
    })
    logic.mount()

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { testy: { key: 'value', name: 'alfred' } },
    })
  })

  test('unique context id each resetContext', async () => {
    resetContext({})
    const contextId1 = getContext().contextId
    resetContext({})
    const contextId2 = getContext().contextId
    resetContext({})
    const contextId3 = getContext().contextId
    expect(contextId1).not.toEqual(contextId2)
    expect(contextId2).not.toEqual(contextId3)
    expect(contextId1).not.toEqual(contextId3)
  })
})
