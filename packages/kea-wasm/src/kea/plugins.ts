import { getContext } from './context'
import { KeaPlugin, PluginEvents } from '../types'

const reservedKeys = {
  key: true,
  path: true,
  pathString: true,
  props: true,
  inputs: true,
  wrapper: true,
  wrap: true,
  build: true,
  mount: true,
  unmount: true,
  isMounted: true,
  findMounted: true,
  findAllMounted: true,
  extend: true,
}

export function activatePlugin(pluginToActivate: KeaPlugin | (() => KeaPlugin)): void {
  const plugin = typeof pluginToActivate === 'function' ? pluginToActivate() : pluginToActivate
  const { plugins } = getContext()

  if (!plugin.name) {
    throw new Error('[KEA] Tried to activate a plugin without a name!')
  }
  if (plugins.activated.find((p) => p.name === plugin.name)) {
    throw new Error(`[KEA] Tried to activate plugin "${plugin.name}", but it was already installed!`)
  }

  plugins.activated.push(plugin)

  if (plugin.defaults) {
    const fields = Object.keys(typeof plugin.defaults === 'function' ? plugin.defaults() : plugin.defaults)
    for (const key of fields) {
      if (plugins.logicFields[key] || (reservedKeys as any)[key]) {
        console.error(
          `[KEA] Plugin "${plugin.name}" redefines logic field "${key}". Previously defined by ${
            plugins.logicFields[key] || 'core'
          }`,
        )
      }
      plugins.logicFields[key] = plugin.name
    }
  }

  if (plugin.events) {
    for (const key of Object.keys(plugin.events) as Array<keyof PluginEvents>) {
      if (!plugins.events[key]) {
        plugins.events[key] = []
      }
      plugins.events[key]!.push(plugin.events[key] as any)
    }

    plugin.events.afterPlugin && plugin.events.afterPlugin()
  }
}

type PluginParameters<T> = T extends (...args: infer P) => any ? P : never

// run plugins with this key with the rest of the arguments
export function runPlugins<T extends keyof PluginEvents, E extends PluginParameters<PluginEvents[T]>>(
  key: T,
  ...args: E
): void {
  const {
    plugins,
    options: { debug },
  } = getContext()
  if (debug) {
    console.log(`[KEA] Event: ${key}`, ...args)
  }
  if (plugins && plugins.events[key]) {
    ;(plugins.events[key] as Array<(...args: E) => void>).forEach((pluginFunction) => {
      pluginFunction(...args)
    })
  }
}
