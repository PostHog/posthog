import { createHash } from 'node:crypto'

/**
 * Esbuild splits a scene into many chunks, and each chunk only declares its own imports, so the
 * browser discovers a scene's files level by level. The chunk map lists every chunk per lazy entry
 * so the scene loader can request them all at once. The map is ~0.5 MB of hashes for the whole
 * app and changes on every deploy, so it is served as its own hashed, immutable static file rather
 * than inlined into the HTML document that every page load has to download and parse first.
 *
 * Only the `index` entry list stays inline: the app entry needs it synchronously at boot, and it
 * is a handful of chunks.
 */
export const CHUNK_MAP_GLOBAL = 'ESBUILD_CHUNK_MAP'

export function chunkMapFileName(entry, chunks) {
    const hash = createHash('sha256').update(JSON.stringify(chunks)).digest('hex').slice(0, 8).toUpperCase()
    return `chunk-map-${entry}-${hash}.js`
}

/** Contents of the external map file: merges the full map into the inline global. */
export function chunkMapFileContents(chunks) {
    return `Object.assign(window.${CHUNK_MAP_GLOBAL} = window.${CHUNK_MAP_GLOBAL} || {}, ${JSON.stringify(chunks)});\n`
}

/**
 * Inline loader script. `chunkMapFile` is the hashed external file, or null to inline the whole
 * map (dev builds serve no map at all and pass `{}`).
 *
 * Scenes requested before the external map arrives are queued and flushed when it loads. The map
 * is a prefetch optimization only: `import()` of the scene module resolves its graph regardless,
 * so a missing or failed map file costs latency, never correctness.
 */
export function chunkLoaderScript(chunks, chunkMapFile) {
    const inlineMap = chunkMapFile ? { index: chunks.index || [] } : chunks
    const loadExternal = chunkMapFile
        ? `
        (function () {
            var pending = [];
            window.ESBUILD_PENDING_CHUNK_SCENES = pending;
            var script = document.createElement('script');
            script.async = true;
            if (document.currentScript && document.currentScript.nonce) {
                script.nonce = document.currentScript.nonce;
            }
            script.src = (window.JS_URL || '') + '/static/' + ${JSON.stringify(chunkMapFile)};
            script.onload = function () {
                window.ESBUILD_PENDING_CHUNK_SCENES = null;
                pending.forEach(function (name) { window.ESBUILD_LOAD_CHUNKS(name); });
            };
            script.onerror = function () {
                window.ESBUILD_PENDING_CHUNK_SCENES = null;
            };
            document.head.appendChild(script);
        })();`
        : ''
    return `
        window.ESBUILD_LOADED_CHUNKS = new Set();
        window.${CHUNK_MAP_GLOBAL} = Object.assign(window.${CHUNK_MAP_GLOBAL} || {}, ${JSON.stringify(inlineMap)});
        window.ESBUILD_LOAD_CHUNKS = function(name) {
            var chunks = window.${CHUNK_MAP_GLOBAL}[name];
            if (!chunks && window.ESBUILD_PENDING_CHUNK_SCENES) {
                window.ESBUILD_PENDING_CHUNK_SCENES.push(name);
                return;
            }
            for (const chunk of chunks || []) {
                if (!window.ESBUILD_LOADED_CHUNKS.has(chunk)) {
                    window.ESBUILD_LOAD_SCRIPT('chunk-'+chunk+'.js');
                    window.ESBUILD_LOADED_CHUNKS.add(chunk);
                }
            }
        }
        window.ESBUILD_LOAD_CHUNKS('index');${loadExternal}
    `
}
