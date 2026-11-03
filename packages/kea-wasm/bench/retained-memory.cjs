// Mounts and unmounts 300 keyed logics that each hold a large state, then reports the heap that
// stays after garbage collection. Run with: node --expose-gc bench/retained-memory.cjs js|wasm
const path=require('path'),fs=require('fs'),Module=require('module')
const repo = path.resolve(__dirname, '../../..')
process.env.NODE_PATH=path.join(repo, 'frontend/node_modules'); Module._initPaths()
const store=path.join(repo, 'node_modules/.pnpm'); const kd=fs.readdirSync(store).find(d=>/^kea@4\.0\.0-pre\.6/.test(d))
const K = process.argv[2]==='wasm' ? require(path.join(__dirname, '../dist/index.cjs.js')) : require(path.join(store,kd,'node_modules/kea/lib/index.cjs.js'))
K.resetContext()
const big = () => new Array(10000).fill(0).map((_, i) => ({ i }))
const logic = K.kea([K.path(k=>['scenes','leak',k]), K.key(p=>p.id), K.actions({set:true}), K.reducers(()=>({ data: [big(), { set: s=>s }], c: [0, {}] })), K.listeners({ set: () => {} })])
for (let i=0;i<300;i++){ const u = logic({id:i}).mount(); u() }
global.gc(); global.gc()
console.log(process.argv[2], 'heapMB', (process.memoryUsage().heapUsed/1e6).toFixed(1))
