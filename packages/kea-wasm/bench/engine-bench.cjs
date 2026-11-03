// Synthetic kea workload. Run one implementation per process:
//   node bench/engine-bench.cjs js|wasm [logicCount ...]
// Prints one JSON line per logic count with the median time of each phase in milliseconds.
const fs = require('fs')
const path = require('path')
const Module = require('module')

const impl = process.argv[2]
const counts = process.argv.slice(3).map(Number)
const repo = path.resolve(__dirname, '../../..')
const frontendModules = path.join(repo, 'frontend/node_modules')
process.env.NODE_PATH = frontendModules
Module._initPaths()

const pnpmStore = path.join(repo, 'node_modules/.pnpm')
const keaDir = fs.readdirSync(pnpmStore).find((d) => /^kea@4\.0\.0-pre\.6/.test(d))
const K =
    impl === 'wasm'
        ? require(path.join(__dirname, '../dist/index.cjs.js'))
        : require(path.join(pnpmStore, keaDir, 'node_modules/kea/lib/index.cjs.js'))

const ROUNDS = 7

function defineLogics(n) {
    const wrappers = []
    for (let i = 0; i < n; i++) {
        const keyed = i % 5 === 0
        const builders = [K.path(['scenes', `area${i % 12}`, `logic${i}`])]
        if (keyed) {
            builders.push(K.key((props) => props.id))
        }
        builders.push(
            K.actions({
                setFilter: (filter) => ({ filter }),
                loadItems: true,
                loadItemsSuccess: (items) => ({ items }),
                loadItemsFailure: (error) => ({ error }),
                toggle: true,
                setPage: (page) => ({ page }),
            }),
            K.reducers({
                filter: ['', { setFilter: (_, { filter }) => filter }],
                items: [[], { loadItemsSuccess: (_, { items }) => items }],
                itemsLoading: [
                    false,
                    { loadItems: () => true, loadItemsSuccess: () => false, loadItemsFailure: () => false },
                ],
                error: [null, { loadItemsFailure: (_, { error }) => error, loadItems: () => null }],
                open: [false, { toggle: (s) => !s }],
                page: [1, { setPage: (_, { page }) => page, setFilter: () => 1 }],
                constant: [{ a: 1 }, {}],
            }),
            K.selectors({
                visibleItems: [(s) => [s.items, s.filter], (items, filter) => items.filter((x) => String(x).includes(filter))],
                count: [(s) => [s.visibleItems], (v) => v.length],
            }),
            K.listeners(({ actions }) => ({
                loadItems: () => {
                    actions.loadItemsSuccess([1, 2, 3])
                },
            }))
        )
        const w = K.kea(builders)
        w.__keyed = keyed
        wrappers.push(w)
    }
    return wrappers
}

function time(fn) {
    const start = process.hrtime.bigint()
    fn()
    return Number(process.hrtime.bigint() - start) / 1e6
}

function median(xs) {
    const s = [...xs].sort((a, b) => a - b)
    return s[Math.floor(s.length / 2)]
}

function runRound(n) {
    K.resetContext({ createStore: true })
    const wrappers = defineLogics(n)
    const built = []
    const unmounts = []
    const result = {}

    result.buildAndMount = time(() => {
        for (const w of wrappers) {
            const logic = w.__keyed ? w({ id: 1 }) : w()
            built.push(logic)
            unmounts.push(logic.mount())
        }
    })

    // One logic's reducer matches. Every other mounted logic's reducers must leave state alone.
    const DISPATCHES = 2000
    result.dispatchOneLogic =
        time(() => {
            for (let i = 0; i < DISPATCHES; i++) {
                built[i % built.length].actions.setFilter(`f${i}`)
            }
        }) / DISPATCHES

    // No reducer matches, like @KEA/FLUSH or an action for an unmounted logic.
    result.dispatchUnmatched =
        time(() => {
            for (let i = 0; i < DISPATCHES; i++) {
                K.getContext().store.dispatch({ type: 'nothing listens to this' })
            }
        }) / DISPATCHES

    // An action that triggers a listener, which dispatches another action.
    result.dispatchWithListener =
        time(() => {
            for (let i = 0; i < DISPATCHES; i++) {
                built[i % built.length].actions.loadItems()
            }
        }) / DISPATCHES

    result.readValues =
        time(() => {
            for (let i = 0; i < DISPATCHES; i++) {
                const v = built[i % built.length].values
                v.count + v.items.length + v.page
            }
        }) / DISPATCHES

    result.unmount = time(() => {
        for (const u of unmounts.reverse()) {
            u()
        }
    })
    return result
}

for (const n of counts) {
    runRound(n) // warm up
    const rounds = []
    for (let r = 0; r < ROUNDS; r++) {
        rounds.push(runRound(n))
    }
    const out = { impl, logics: n }
    for (const key of Object.keys(rounds[0])) {
        out[key] = median(rounds.map((r) => r[key]))
    }
    if (impl === 'wasm' && K.__keaWasmEngineStats) {
        out.engine = K.__keaWasmEngineStats()
    }
    console.log(JSON.stringify(out))
}
