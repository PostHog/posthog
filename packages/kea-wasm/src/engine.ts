// Loads the Rust engine synchronously. Kea opens its default context when the module loads,
// so the WebAssembly module must be ready before any other module code runs.
import { initSync, Engine, LogicHandle, MappingHandle, createActionType, engineStats, resetEngineStats } from '../gen/kea_wasm_engine.js'
import { wasmBase64 } from '../gen/wasm-base64.js'

function decodeBase64(base64: string): Uint8Array {
    const binary = atob(base64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i)
    }
    return bytes
}

initSync({ module: decodeBase64(wasmBase64) })

export { Engine, LogicHandle, MappingHandle, createActionType, engineStats, resetEngineStats }

/** The generated root reducer of a logic, mapped to the engine handle and slot array that run it. */
export const generatedLogicReducers = new WeakMap<Function, { handle: LogicHandle; slots: Function[] }>()

/** A key reducer that kea generated, mapped to its owner and its action mapping. */
export const generatedKeyReducers = new WeakMap<Function, { owner: LogicHandle; mapping: MappingHandle | null }>()

/** The engine handle of each built logic. */
export const logicHandles = new WeakMap<object, LogicHandle>()

/** The engine handle of each reducer mapping object in `logic.cache.reducers`. */
export const mappingHandles = new WeakMap<object, MappingHandle>()

/**
 * The functions of a logic that the engine calls, by slot index. The engine stores only the
 * indices, so it never keeps a logic alive. See crate/src/lib.rs.
 */
export type LogicSlots = { slots: Function[]; index: Map<Function, number> }
export const logicSlots = new WeakMap<object, LogicSlots>()

export function slotOf(logic: object, fn: Function): number {
  let entry = logicSlots.get(logic)
  if (!entry) {
    entry = { slots: [], index: new Map() }
    logicSlots.set(logic, entry)
  }
  let slot = entry.index.get(fn)
  if (slot === undefined) {
    slot = entry.slots.length
    entry.slots.push(fn)
    entry.index.set(fn, slot)
  }
  return slot
}

export function slotsOf(logic: object): Function[] {
  let entry = logicSlots.get(logic)
  if (!entry) {
    entry = { slots: [], index: new Map() }
    logicSlots.set(logic, entry)
  }
  return entry.slots
}

function probe(depth: number): number {
  return depth === 0 ? 0 : probe(depth - 1) + 1
}

/**
 * Throws the JavaScript RangeError for a full stack before an engine call that runs user code.
 * A stack overflow that unwinds through WebAssembly frames skips Rust destructors and can leave
 * the engine in a broken state. With this check, the overflow happens in JavaScript, like in kea.
 */
export function ensureStackHeadroom(): void {
  probe(STACK_HEADROOM_FRAMES)
}

const STACK_HEADROOM_FRAMES = 96
