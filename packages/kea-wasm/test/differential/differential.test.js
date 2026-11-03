// Differential test: runs the same random scenario against kea@4.0.0-pre.6 and kea-wasm, and
// compares them after every step. It compares the store state, the subtrees whose identity
// changed (selectors depend on identity), the calls to user reducers and listeners, and errors.
import * as wasmKea from '../../src'

const path = require('path')
const fs = require('fs')

const pnpmStore = path.resolve(__dirname, '../../../../node_modules/.pnpm')
const keaDir = fs.readdirSync(pnpmStore).find((d) => /^kea@4\.0\.0-pre\.6/.test(d))
const originalKea = require(path.join(pnpmStore, keaDir, 'node_modules/kea/src'))

function mulberry32(seed) {
    return function () {
        seed |= 0
        seed = (seed + 0x6d2b79f5) | 0
        let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

function changedPaths(prev, next, prefix = '', out = []) {
    if (prev === next) {
        return out
    }
    out.push(prefix || '<root>')
    if (prev && next && typeof prev === 'object' && typeof next === 'object') {
        for (const key of new Set([...Object.keys(prev), ...Object.keys(next)])) {
            changedPaths(prev[key], next[key], `${prefix}.${key}`, out)
        }
    }
    return out
}

function runScenario(K, seed, steps) {
    const rng = mulberry32(seed)
    const pick = (arr) => arr[Math.floor(rng() * arr.length)]
    const chance = (p) => rng() < p
    const log = []
    const trace = []

    K.resetContext({ createStore: true })

    const logicCount = 4 + Math.floor(rng() * 8)
    const wrappers = []
    const actionNames = ['go', 'set', 'bump', 'reset', 'noop']

    for (let i = 0; i < logicCount; i++) {
        const builders = []
        const keyed = chance(0.3)
        const pathKind = rng()
        if (pathKind < 0.6) {
            const parts = [pick(['scenes', 'models', 'kea']), `l${i}`]
            if (chance(0.3)) {
                parts.push(pick(['inner', '7', '12', 'x']))
            }
            builders.push(K.path(parts))
        }
        if (keyed) {
            builders.push(K.key((props) => props.id))
        }
        const myActions = actionNames.slice(0, 2 + Math.floor(rng() * 3))
        builders.push(
            K.actions(Object.fromEntries(myActions.map((a) => [a, (v = 1) => ({ v })])))
        )

        // Reducers keyed by own action names, by other logics' action types, and empty mappings.
        const reducerCount = 1 + Math.floor(rng() * 4)
        const reducerSpecs = []
        for (let r = 0; r < reducerCount; r++) {
            const mode = rng()
            const listens = []
            if (mode > 0.15) {
                for (const a of myActions) {
                    if (chance(0.5)) {
                        listens.push({ own: a })
                    }
                }
                if (i > 0 && chance(0.5)) {
                    const other = Math.floor(rng() * i)
                    listens.push({ other, action: pick(actionNames.slice(0, 2)) })
                }
            }
            reducerSpecs.push({ name: `r${r}`, listens, initial: pick([0, 'x', null, { n: 0 }]), op: pick(['add', 'same', 'obj']) })
        }
        builders.push(
            K.reducers((logic) =>
                Object.fromEntries(
                    reducerSpecs.map((spec) => {
                        const mapping = {}
                        for (const l of spec.listens) {
                            const reducer = (state, payload) => {
                                log.push(['reducer', i, spec.name, JSON.stringify(state), JSON.stringify(payload)])
                                if (spec.op === 'same') {
                                    return state
                                }
                                if (spec.op === 'obj') {
                                    return { n: payload.v }
                                }
                                return typeof state === 'number' ? state + payload.v : payload.v
                            }
                            if ('own' in l) {
                                mapping[l.own] = reducer
                            } else {
                                const otherWrapper = wrappers[l.other]
                                // Action types of other logics, as strings. Keyed logics use key 1.
                                const otherLogic = otherWrapper.__keyed ? otherWrapper({ id: 1 }) : otherWrapper()
                                if (otherLogic.actionTypes[l.action]) {
                                    mapping[otherLogic.actionTypes[l.action]] = reducer
                                }
                            }
                        }
                        return [spec.name, [spec.initial, mapping]]
                    })
                )
            )
        )
        if (chance(0.5)) {
            builders.push(
                K.selectors({
                    derived: [(s) => [s.r0], (r0) => ({ r0 })],
                })
            )
        }
        if (chance(0.4) && i > 0) {
            const target = Math.floor(rng() * i)
            const trigger = pick(myActions)
            builders.push(
                K.listeners(() => ({
                    [trigger]: (payload) => {
                        log.push(['listener', i, trigger, JSON.stringify(payload)])
                        const t = wrappers[target]
                        const built = t.__keyed ? t.findMounted({ id: 1 }) : t.findMounted()
                        if (built && payload.v < 4) {
                            built.actions.go(payload.v + 1)
                        }
                    },
                }))
            )
        }
        const wrapper = K.kea(builders)
        wrapper.__keyed = keyed
        wrappers.push(wrapper)
    }

    const unmounters = []
    let previousState = K.getContext().store.getState()

    for (let step = 0; step < steps; step++) {
        const op = rng()
        let description
        let error = null
        try {
            if (op < 0.25 || unmounters.length === 0) {
                const w = Math.floor(rng() * wrappers.length)
                const id = 1 + Math.floor(rng() * 2)
                description = `mount ${w} ${id}`
                const built = wrappers[w].__keyed ? wrappers[w]({ id }) : wrappers[w]()
                unmounters.push({ w, id, unmount: built.mount() })
            } else if (op < 0.35) {
                const index = Math.floor(rng() * unmounters.length)
                const [{ w, id, unmount }] = unmounters.splice(index, 1)
                description = `unmount ${w} ${id}`
                unmount()
            } else if (op < 0.85) {
                const { w, id } = pick(unmounters)
                const wrapper = wrappers[w]
                const built = wrapper.__keyed ? wrapper({ id }) : wrapper()
                const actionKey = pick(Object.keys(built.actions))
                const v = Math.floor(rng() * 3)
                description = `dispatch ${w} ${id} ${actionKey} ${v}`
                built.actions[actionKey](v)
            } else if (op < 0.9) {
                description = 'dispatch unknown'
                K.getContext().store.dispatch({ type: 'unknown action', payload: 1 })
            } else if (op < 0.93) {
                // Change a default after mount. Reducers without actions return the default.
                const { w, id } = pick(unmounters)
                const wrapper = wrappers[w]
                const built = wrapper.__keyed ? wrapper({ id }) : wrapper()
                // Prefer reducers without actions: they return the default on every dispatch.
                const keys = Object.keys(built.reducers)
                const constantKeys = keys.filter((k) => Object.keys(built.cache.reducers?.[k] ?? {}).length === 0)
                const key = pick(constantKeys.length > 0 && chance(0.8) ? constantKeys : keys)
                description = `defaults ${w} ${id} ${key}`
                built.extend(K.defaults({ [key]: `d${step}` }))
                K.getContext().store.dispatch({ type: 'after defaults' })
            } else if (op < 0.95) {
                // Add a reducer to a mounted logic, which changes its mapping after mount.
                const { w, id } = pick(unmounters)
                const wrapper = wrappers[w]
                const built = wrapper.__keyed ? wrapper({ id }) : wrapper()
                const extra = `late${step}`
                const listenTo = pick(Object.keys(built.actions))
                description = `extend ${w} ${id} ${extra} ${listenTo}`
                built.extend(
                    K.reducers({
                        [extra]: [
                            0,
                            {
                                [listenTo]: (state, payload) => {
                                    log.push(['late', w, extra, state, JSON.stringify(payload)])
                                    return state + payload.v + 1
                                },
                            },
                        ],
                    }),
                )
                // The new key has no state until the next dispatch reaches the logic.
                K.getContext().store.dispatch({ type: 'after extend' })
            } else {
                // Replace a key reducer with a wrapper, like kea-localstorage does.
                const { w, id } = pick(unmounters)
                const wrapper = wrappers[w]
                const built = wrapper.__keyed ? wrapper({ id }) : wrapper()
                const key = pick(Object.keys(built.reducers))
                description = `wrap ${w} ${id} ${key}`
                const inner = built.reducers[key]
                built.reducers[key] = (state, action, fullState) => {
                    log.push(['wrapped', w, key, action.type])
                    return inner(state, action, fullState)
                }
            }
        } catch (e) {
            error = e.message
        }
        const state = K.getContext().store.getState()
        trace.push({
            step,
            description,
            error,
            state: JSON.stringify(state),
            changed: changedPaths(previousState, state),
            log: log.splice(0),
            mounted: Object.keys(K.getContext().mount.mounted).sort(),
        })
        previousState = state
    }
    return trace
}

describe('kea-wasm against kea', () => {
    const seeds = Array.from({ length: 60 }, (_, i) => i + 1)
    test.each(seeds)('random scenario %i matches step by step', (seed) => {
        const expected = runScenario(originalKea, seed, 120)
        const actual = runScenario(wasmKea, seed, 120)
        for (let i = 0; i < expected.length; i++) {
            expect({ ...actual[i], seed }).toEqual({ ...expected[i], seed })
        }
    })
})

describe('stack overflow', () => {
    function overflowScenario(K) {
        K.resetContext()
        const out = []
        const loop = K.kea([
            K.path(['scenes', 'loop']),
            K.actions({ ping: true, other: true }),
            K.reducers({ pings: [0, { ping: (s) => s + 1 }], others: [0, { other: (s) => s + 1 }] }),
            K.listeners(({ actions }) => ({ ping: () => actions.ping() })),
        ])
        const bystander = K.kea([K.path(['scenes', 'bystander']), K.actions({ hit: true }), K.reducers({ hits: [0, { hit: (s) => s + 1 }] })])
        loop.mount()
        bystander.mount()
        try {
            loop.actions.ping()
            out.push('no error')
        } catch (e) {
            out.push(e.constructor.name, /Maximum call stack/.test(e.message))
        }
        // After the overflow, the store, mounting and listeners must still work.
        bystander.actions.hit()
        loop.actions.other()
        const late = K.kea([K.path(['scenes', 'late']), K.reducers({ x: [1, {}] })])
        const unmount = late.mount()
        out.push(K.getContext().store.getState().scenes.bystander, K.getContext().store.getState().scenes.late)
        unmount()
        bystander.unmount()
        out.push(Object.keys(K.getContext().store.getState().scenes), Object.keys(K.getContext().mount.mounted))
        out.push(loop.values.others)
        return out
    }

    test('a listener loop throws RangeError and the store keeps working', () => {
        const expected = overflowScenario(originalKea)
        expect(expected[0]).toEqual('RangeError')
        expect(overflowScenario(wasmKea)).toEqual(expected)
    })
})
