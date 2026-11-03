import { kea, resetContext, getContext, getPluginContext, setPluginContext, activatePlugin } from '../../src'
import { corePlugin } from '../../src'

describe('plugins', () => {
  test('the core plugin is activated automatically', () => {
    resetContext()
    const { plugins } = getContext()

    expect(plugins.activated).toEqual([corePlugin])
  })

  test('plugins add events', () => {
    resetContext()
    const { plugins } = getContext()

    const testPlugin = {
      name: 'test',

      defaults: () => ({
        ranAfterBuild: false,
      }),

      events: {
        afterBuild(logic, inputs) {
          logic.ranAfterBuild = true
        },
      },
    }

    activatePlugin(testPlugin)

    expect(plugins.activated).toEqual([corePlugin, testPlugin])
    expect(Object.keys(plugins.events)).toEqual(['afterPlugin', 'beforeReduxStore', 'legacyBuild', 'afterBuild'])

    expect(plugins.events.afterBuild).toEqual([testPlugin.events.afterBuild])

    const logic = kea({})

    expect(logic.build().ranAfterBuild).toEqual(true)
  })

  test('function plugins work', () => {
    resetContext()
    const { plugins } = getContext()

    const testPluginContents = {
      name: 'test',

      defaults: () => ({
        ranAfterBuild: false,
      }),

      events: {
        afterBuild(logic, inputs) {
          logic.ranAfterBuild = true
        },
      },
    }
    const testPlugin = () => testPluginContents

    activatePlugin(testPlugin)

    expect(plugins.activated).toEqual([corePlugin, testPluginContents])
    expect(Object.keys(plugins.events)).toEqual(['afterPlugin', 'beforeReduxStore', 'legacyBuild', 'afterBuild'])

    expect(plugins.events.afterBuild).toEqual([testPluginContents.events.afterBuild])

    const logic = kea({})

    expect(logic.build().ranAfterBuild).toEqual(true)
  })

  test('plugin context & afterPlugin work', () => {
    resetContext()
    const { plugins } = getContext()

    const testPlugin = {
      name: 'test',

      defaults: () => ({
        ranAfterBuild: null,
      }),

      events: {
        afterPlugin() {
          setPluginContext('pluginName', { someKey: 'yesplease' })
        },

        afterBuild(logic, inputs) {
          logic.ranAfterBuild = getPluginContext('pluginName').someKey
        },
      },
    }

    activatePlugin(testPlugin)

    expect(plugins.activated).toEqual([corePlugin, testPlugin])
    expect(Object.keys(plugins.events)).toEqual(['afterPlugin', 'beforeReduxStore', 'legacyBuild', 'afterBuild'])
    expect(plugins.events.afterBuild).toEqual([testPlugin.events.afterBuild])

    const logic = kea({})

    expect(logic.build().ranAfterBuild).toEqual('yesplease')
  })

  test('can use logic.cache to store things', () => {
    resetContext()
    const { plugins } = getContext()

    let checkedAfterMount = false

    const testPlugin = {
      name: 'test',

      events: {
        afterLogic(logic) {
          logic.cache.whatever = true
        },
        afterMount(logic) {
          checkedAfterMount = logic.cache.whatever
        },
      },
    }

    activatePlugin(testPlugin)

    expect(plugins.activated).toEqual([corePlugin, testPlugin])
    expect(Object.keys(plugins.events)).toEqual([
      'afterPlugin',
      'beforeReduxStore',
      'legacyBuild',
      'afterLogic',
      'afterMount',
    ])

    const logic = kea({})
    logic.mount()

    expect(logic.cache.whatever).toEqual(true)
    expect(checkedAfterMount).toEqual(true)
  })

  test('can not activate the same plugin twice', () => {
    resetContext()

    const testPlugin = {
      name: 'test',

      events: {
        afterLogic(logic) {
          logic.cache.whatever = true
        },
      },
    }

    activatePlugin(testPlugin)

    expect(() => {
      activatePlugin(testPlugin)
    }).toThrow()
  })
})
