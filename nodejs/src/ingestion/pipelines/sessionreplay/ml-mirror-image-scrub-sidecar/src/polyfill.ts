/**
 * Node 23+ removed the legacy util.is* helpers; @tensorflow/tfjs-node still calls them and crashes
 * without this. Import this module FIRST, before anything that loads tfjs-node.
 */
import util from 'node:util'

const u = util as unknown as Record<string, unknown>
u.isNullOrUndefined ??= (v: unknown) => v === null || v === undefined
u.isNull ??= (v: unknown) => v === null
u.isUndefined ??= (v: unknown) => v === undefined
u.isArray ??= Array.isArray
u.isFunction ??= (v: unknown) => typeof v === 'function'
u.isString ??= (v: unknown) => typeof v === 'string'
u.isNumber ??= (v: unknown) => typeof v === 'number'
u.isObject ??= (v: unknown) => typeof v === 'object' && v !== null
