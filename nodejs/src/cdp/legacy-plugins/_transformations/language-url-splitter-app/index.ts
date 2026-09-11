import { Script } from 'node:vm'

import { PluginEvent } from '~/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

const DEFAULT_PATTERN = '^/([a-z]{2})(?=/|#|\\?|$)'
const DEFAULT_REPLACE_PATTERN = '^(/[a-z]{2})(/|(?=/|#|\\?|$))'
const defaultRegexp = new RegExp(DEFAULT_PATTERN)
const defaultReplaceRegexp = new RegExp(DEFAULT_REPLACE_PATTERN)

// Keep patterns and input out of the program source so only synchronous regex work runs in the VM.
const matchScript = new Script('pathname.match(new RegExp(pattern))')
const replaceScript = new Script('const regexp = new RegExp(pattern); pathname.replace(regexp, replacement)')

function runWithDeadline<T>(script: Script, data: Record<string, unknown>): T {
    try {
        return script.runInNewContext(data, {
            timeout: 50,
            contextCodeGeneration: { strings: false, wasm: false },
        }) as T
    } catch (error) {
        // VM errors have a different prototype; preserve the executor's native Error handling.
        const ErrorConstructor =
            error.name === 'SyntaxError' ? SyntaxError : error.name === 'TypeError' ? TypeError : Error
        const wrapped = new ErrorConstructor(error.message, { cause: error })
        if (error.code) {
            Object.assign(wrapped, { code: error.code })
        }
        throw wrapped
    }
}

export function processEvent(event: PluginEvent, { config }: LegacyTransformationPluginMeta): PluginEvent {
    const { pattern, matchGroup, property, replacePattern, replaceKey, replaceValue } = config
    if (event.properties && typeof event.properties['$pathname'] === 'string') {
        // These exact shipped patterns inspect a fixed prefix; custom patterns require an engine deadline.
        const match =
            pattern === DEFAULT_PATTERN
                ? event.properties['$pathname'].match(defaultRegexp)
                : runWithDeadline<RegExpMatchArray | null>(matchScript, {
                      pathname: event.properties['$pathname'],
                      pattern,
                  })
        if (match) {
            event.properties[property] = match[matchGroup]
            if (replacePattern) {
                event.properties[replaceKey] =
                    replacePattern === DEFAULT_REPLACE_PATTERN
                        ? event.properties['$pathname'].replace(defaultReplaceRegexp, replaceValue)
                        : runWithDeadline<string>(replaceScript, {
                              pathname: event.properties['$pathname'],
                              pattern: replacePattern,
                              replacement: replaceValue,
                          })
            }
        }
    }
    return event
}
