import { Scanner } from '@tailwindcss/oxide'
import { build } from 'esbuild'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'tailwindcss'

// The platform contract (pinned dependencies, CSP, size limits) is shared with
// the Python validator and the artifact origin via manifest.json — edit it
// there, never inline here.
const contract = JSON.parse(readFileSync(new URL('./manifest.json', import.meta.url), 'utf8'))
const admitted = Object.fromEntries(
    Object.entries(contract.dependencies).map(([name, entry]) => [name, [entry.version, entry.url]])
)
const runtimeImports = contract.runtimeImports
const csp = contract.csp
const builderDirectory = path.dirname(fileURLToPath(import.meta.url))
const builderRequire = createRequire(import.meta.url)
const htmlTag = /<(script|link)\b[^>]*>/gi
const htmlAttribute = /([a-zA-Z][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g
const forbiddenHtml = /(?:src|href)\s*=\s*["']\s*(javascript|data:text\/html|vbscript)/i
const extensions = ['', '.ts', '.tsx', '.js', '.jsx', '.css', '.json', '.svg', '.txt']
const runtimePath = 'assets/canvas-runtime.js'
// The host only delivers the MessagePort after the artifact iframe's load
// event, which fires after the app's module scripts have already run, so any
// ph.* call issued during mount lands before the port exists. Those messages
// queue (bounded, in case the host never connects) and flush on connect.
const runtime = `(()=>{const channel="posthog-canvas",pending=new Map,queued=[];let sequence=0,port;const post=(message)=>{const payload={channel,...message};if(port){port.postMessage(payload)}else if(queued.length<256){queued.push(payload)}};const call=(method,payload)=>new Promise((resolve,reject)=>{if(!port&&(method==="actionInvoke"||method==="agentRequest")){reject(new Error("Canvas actions require a user action"));return}const id=String(++sequence);const timer=setTimeout(()=>{pending.delete(id);const queuedIndex=queued.findIndex((message)=>message.type==="data-request"&&message.id===id);if(queuedIndex>-1)queued.splice(queuedIndex,1);reject(new Error("Canvas request timed out"));},30000);pending.set(id,{resolve,reject,timer});post({type:"data-request",id,method,payload});});const applyTheme=(theme)=>{if(theme!=="dark"&&theme!=="light")return;const dark=theme==="dark";document.documentElement.classList.toggle("dark",dark);document.documentElement.style.colorScheme=dark?"dark":"light";};const fragmentParams=new URLSearchParams(location.hash.slice(1));applyTheme(fragmentParams.get("theme"));let config={};try{const rawConfig=fragmentParams.get("config");if(rawConfig)config=Object.freeze(JSON.parse(rawConfig))}catch{config={}};const receive=(event)=>{if(event.data?.channel!==channel)return;if(event.data.type==="set-theme"){applyTheme(event.data.theme);return}if(event.data.type!=="data-response")return;const request=pending.get(event.data.id);if(!request)return;pending.delete(event.data.id);clearTimeout(request.timer);event.data.ok?request.resolve(event.data.result):request.reject(new Error(event.data.error??"Canvas request failed"));};const capture=(event,properties,distinctId)=>{const normalized=properties??{};let serialized;try{serialized=JSON.stringify(normalized)}catch{throw new Error("Canvas capture properties must be serializable")};if(typeof serialized!=="string"||serialized.length>16384)throw new Error("Canvas capture properties are too large");return call("capture",{event,properties:normalized,distinctId})};const openExternal=(value)=>{const url=new URL(value);if(url.protocol!=="https:"||!(url.hostname==="posthog.com"||url.hostname.endsWith(".posthog.com")))throw new Error("Canvas external URL is not allowed");post({type:"open-external",url:url.href})};window.ph={config,loadInsight:(shortId,options)=>call("loadInsight",{shortId,dateRange:options?.dateRange,variables:options?.variables,refresh:options?.refresh}),query:(query,params,options)=>call("query",typeof query==="string"?{hogql:query,params:params??{},refresh:options?.refresh}:{query,params:params??{},refresh:options?.refresh}),capture,openExternal,agent:{request:(prompt)=>call("agentRequest",{prompt})},state:{get:(key,opts)=>call("stateGet",{key,scope:opts?.scope||"user"}),set:(key,value,opts)=>call("stateSet",{key,value:value===undefined?null:value,scope:opts?.scope||"user"}),list:(opts)=>call("stateList",{scope:opts?.scope})},actions:{invoke:(verb,payload)=>call("actionInvoke",{verb,payload:payload??{}})}};addEventListener("message",(event)=>{if(port||event.source!==parent||event.data?.channel!==channel||event.data?.type!=="connect"||!event.ports[0])return;port=event.ports[0];port.addEventListener("message",receive);port.start();while(queued.length)port.postMessage(queued.shift());if(document.readyState!=="loading")post({type:"ready"});if(document.readyState==="complete")post({type:"rendered"});});addEventListener("error",(event)=>post({type:"error",message:event.message||"Canvas runtime error",stack:event.error?.stack}));addEventListener("unhandledrejection",(event)=>post({type:"error",message:event.reason instanceof Error?event.reason.message:String(event.reason),stack:event.reason instanceof Error?event.reason.stack:undefined}));const cspSeen=new Set();addEventListener("securitypolicyviolation",(event)=>{const directive=event.effectiveDirective||"unknown";if(cspSeen.has(directive))return;cspSeen.add(directive);post({type:"error",message:"SecurityPolicyViolationError: "+directive})});addEventListener("DOMContentLoaded",()=>post({type:"ready"}));addEventListener("load",()=>post({type:"rendered"}));})();`
// A published canvas runs the runtime baked into its artifact by this builder,
// while an unpublished one runs the desktop's sandbox document — two copies of
// the same selection behavior. The pair below is ported from the desktop's
// selectionCommentAction.ts (commentActionAnchorRect, installSelectionSettleGate)
// because this builder ships inside its own build image and cannot import that
// workspace. Change one, change the other: test_cloud_builder.py drives this
// copy through a simulated drag with the desktop suite's expectations.

// Which box the comment action anchors to. A Range spanning block elements also
// reports the wrapper boxes (paragraph, blockquote, list), so neither the
// bounding box nor the last entry marks where the user stopped selecting.
// Check boxes from visually last to first and take the first leaf box, which
// avoids scanning every pair for normal selections.
function commentActionAnchorRect(rects, fallback) {
    const boxes = []
    for (let index = 0; index < rects.length; index++) {
        const rect = rects[index]
        if (rect.width > 0 || rect.height > 0) {
            boxes.push(rect)
        }
    }
    if (boxes.length === 0) {
        return fallback
    }
    const EPSILON = 0.5
    const area = (box) => box.width * box.height
    const encloses = (outer, inner) =>
        area(outer) > area(inner) + 1 &&
        outer.left <= inner.left + EPSILON &&
        outer.right >= inner.right - EPSILON &&
        outer.top <= inner.top + EPSILON &&
        outer.bottom >= inner.bottom - EPSILON
    const candidates = boxes.slice().sort((left, right) => {
        const verticalDistance = right.bottom - left.bottom
        return Math.abs(verticalDistance) > EPSILON ? verticalDistance : right.right - left.right
    })
    for (const box of candidates) {
        if (!boxes.some((other) => other !== box && encloses(box, other))) {
            return box
        }
    }
    return candidates[0]
}

// While the user selects, the range keeps moving, so an action anchored to the
// live selection chases the cursor. The gate reports only settled selections:
//
//   selectstart / pointerdown / selection keydown -> hide
//   selectionchange                               -> ignore while gesturing
//   pointerup / selection keyup                   -> report, two frames later
//   pointercancel / blur                          -> cancel
//
// The two frames matter: the browser commits the selection AFTER the pointerup
// handler runs, so reading it synchronously returns the mid-gesture range.
function installSelectionSettleGate(doc, callbacks) {
    const view = doc.defaultView
    let selecting = false
    let keyGesture = false
    let frame = 0

    // Keys that move or extend a selection. "a" only counts with a modifier, so
    // typing the letter doesn't read as select-all.
    const isSelectionKey = (event) => {
        if (event.key === 'a' || event.key === 'A') {
            return event.metaKey || event.ctrlKey
        }
        return (
            event.key === 'Shift' ||
            event.key === 'Home' ||
            event.key === 'End' ||
            event.key === 'PageUp' ||
            event.key === 'PageDown' ||
            event.key.startsWith('Arrow')
        )
    }

    const cancelFrame = () => {
        if (frame && view?.cancelAnimationFrame) {
            view.cancelAnimationFrame(frame)
        }
        frame = 0
    }
    const settle = () => {
        cancelFrame()
        const request = view?.requestAnimationFrame
        if (!request) {
            callbacks.onSelectionSettled?.()
            return
        }
        frame = request.call(view, () => {
            frame = request.call(view, () => {
                frame = 0
                callbacks.onSelectionSettled?.()
            })
        })
    }
    const inActionUi = (target) => target instanceof Element && !!target.closest('[data-selection-comment-overlay]')
    const startGesture = () => {
        if (selecting) {
            return
        }
        selecting = true
        cancelFrame()
        callbacks.onGestureStart?.()
    }
    const cancelGesture = () => {
        if (!selecting) {
            return
        }
        selecting = false
        keyGesture = false
        cancelFrame()
        callbacks.onGestureCancel?.()
    }

    const onPointerDown = (event) => {
        // Secondary buttons open menus; they don't select.
        if (event instanceof MouseEvent && event.button > 0) {
            return
        }
        if (inActionUi(event.target)) {
            return
        }
        startGesture()
    }
    // Catches drags whose pointerdown we never saw, and keyboard selections.
    const onSelectStart = (event) => {
        if (inActionUi(event.target)) {
            return
        }
        startGesture()
    }
    const onPointerUp = (event) => {
        if (event instanceof MouseEvent && event.button > 0) {
            return
        }
        if (!selecting) {
            return
        }
        selecting = false
        keyGesture = false
        settle()
    }
    const onKeyDown = (event) => {
        if (!isSelectionKey(event)) {
            return
        }
        keyGesture = true
        startGesture()
    }
    const onKeyUp = () => {
        if (!selecting || !keyGesture) {
            return
        }
        selecting = false
        keyGesture = false
        settle()
    }
    const onSelectionChange = () => {
        if (selecting) {
            return
        }
        callbacks.onIdleSelectionChange?.()
    }

    doc.addEventListener('pointerdown', onPointerDown, true)
    doc.addEventListener('selectstart', onSelectStart, true)
    doc.addEventListener('pointerup', onPointerUp, true)
    doc.addEventListener('pointercancel', cancelGesture, true)
    doc.addEventListener('keydown', onKeyDown, true)
    doc.addEventListener('keyup', onKeyUp, true)
    doc.addEventListener('selectionchange', onSelectionChange)
    view?.addEventListener('blur', cancelGesture)
    return () => {
        cancelFrame()
        doc.removeEventListener('pointerdown', onPointerDown, true)
        doc.removeEventListener('selectstart', onSelectStart, true)
        doc.removeEventListener('pointerup', onPointerUp, true)
        doc.removeEventListener('pointercancel', cancelGesture, true)
        doc.removeEventListener('keydown', onKeyDown, true)
        doc.removeEventListener('keyup', onKeyUp, true)
        doc.removeEventListener('selectionchange', onSelectionChange)
        view?.removeEventListener('blur', cancelGesture)
    }
}

const selectionRuntime = `(()=>{const channel="posthog-canvas";let port,timer=0,published=false;const anchorRect=${commentActionAnchorRect.toString()};const settleGate=${installSelectionSettleGate.toString()};const post=message=>port?.postMessage({channel,...message}),clear=()=>{if(!published)return;published=false;post({type:"text-selection-cleared"})},clearNative=()=>{getSelection()?.removeAllRanges();clear()},report=()=>{clearTimeout(timer);timer=setTimeout(()=>{const selection=getSelection();if(!selection||selection.isCollapsed||selection.rangeCount===0){clear();return}const range=selection.getRangeAt(0);if(!document.body.contains(range.startContainer)||!document.body.contains(range.endContainer)){clear();return}const before=document.createRange();before.selectNodeContents(document.body);before.setEnd(range.startContainer,range.startOffset);const through=document.createRange();through.selectNodeContents(document.body);through.setEnd(range.endContainer,range.endOffset);const whole=document.createRange();whole.selectNodeContents(document.body);const text=whole.toString(),start=before.toString().length,end=through.toString().length,quote=text.slice(start,end);if(!quote.trim()||quote.length>10000){clear();return}const rect=anchorRect(range.getClientRects?range.getClientRects():[],range.getBoundingClientRect());published=true;post({type:"text-selection",selection:{quote,prefix:text.slice(Math.max(0,start-32),start),suffix:text.slice(end,end+32),start,end,rect:{top:rect.top,right:rect.right,bottom:rect.bottom,left:rect.left}}})},80)};addEventListener("message",event=>{if(port||event.source!==parent||event.data?.channel!==channel||event.data?.type!=="connect"||!event.ports[0])return;port=event.ports[0];port.addEventListener("message",event=>{if(event.data?.channel===channel&&event.data?.type==="clear-text-selection")clearNative()});port.start()});const abort=()=>{clearTimeout(timer);clear()};settleGate(document,{onGestureStart:abort,onSelectionSettled:report,onIdleSelectionChange:report,onGestureCancel:abort});document.addEventListener("scroll",abort,true)})();`
const highlightRuntime = `(()=>{const channel="posthog-canvas",style=document.createElement("style");style.textContent="::highlight(posthog-canvas-comment){background:rgba(250,204,21,.32);color:inherit}::highlight(posthog-canvas-comment-active){background:rgba(250,204,21,.48);color:inherit}";document.head.appendChild(style);let items=[],ranges=[],port,timer=0;const indexText=()=>{const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),entries=[];let text="";for(let node=walker.nextNode();node;node=walker.nextNode()){const start=text.length;text+=node.data;entries.push({node,start,end:text.length})}return{text,entries}},rangeAt=(index,start,end)=>{const find=offset=>{let low=0,high=index.entries.length-1,match=null;while(low<=high){const middle=low+high>>1,entry=index.entries[middle];if(offset<entry.start)high=middle-1;else if(offset>entry.end)low=middle+1;else{match=entry;high=middle-1}}return match},startEntry=find(start),endEntry=find(end);if(!startEntry||!endEntry)return null;const range=document.createRange();range.setStart(startEntry.node,start-startEntry.start);range.setEnd(endEntry.node,end-endEntry.start);return range},resolve=(text,anchor)=>{if(text.slice(anchor.start,anchor.end)===anchor.quote)return{start:anchor.start,end:anchor.end};const matches=[];for(let start=text.indexOf(anchor.quote);start>=0;start=text.indexOf(anchor.quote,start+Math.max(anchor.quote.length,1))){const end=start+anchor.quote.length,prefix=text.slice(Math.max(0,start-anchor.prefix.length),start),suffix=text.slice(end,end+anchor.suffix.length);matches.push({start,end,score:(anchor.prefix&&prefix===anchor.prefix?2:0)+(anchor.suffix&&suffix===anchor.suffix?2:0)})}if(matches.length===1)return matches[0];matches.sort((a,b)=>b.score-a.score);return matches[0]?.score&&matches[0].score!==matches[1]?.score?matches[0]:null},render=next=>{items=next||[];ranges=[];if(!window.Highlight||!window.CSS||!CSS.highlights)return;const normal=new Highlight,active=new Highlight,index=indexText();for(const item of items){const hit=resolve(index.text,item.anchor),range=hit&&rangeAt(index,hit.start,hit.end);if(range){ranges.push({id:item.id,range});(item.active?active:normal).add(range)}}CSS.highlights.set("posthog-canvas-comment",normal);CSS.highlights.set("posthog-canvas-comment-active",active)};addEventListener("message",event=>{if(port||event.source!==parent||event.data?.channel!==channel||event.data?.type!=="connect"||!event.ports[0])return;port=event.ports[0];port.addEventListener("message",event=>{if(event.data?.channel===channel&&event.data?.type==="set-comment-highlights")render(event.data.highlights)});port.start()});document.addEventListener("click",event=>{const selection=getSelection();if(selection&&!selection.isCollapsed)return;for(const item of ranges)for(const rect of item.range.getClientRects())if(event.clientX>=rect.left&&event.clientX<=rect.right&&event.clientY>=rect.top&&event.clientY<=rect.bottom){event.preventDefault();event.stopPropagation();port?.postMessage({channel,type:"comment-activate",id:item.id});return}},true);const observeBody=()=>new MutationObserver(()=>{if(!items.length||timer)return;timer=setTimeout(()=>{timer=0;render(items)},500)}).observe(document.body,{childList:true,characterData:true,subtree:true});document.body?observeBody():addEventListener("DOMContentLoaded",observeBody)})();`
const keyboardRuntime = `(()=>{const channel="posthog-canvas";let port;addEventListener("message",event=>{if(port||event.source!==parent||event.data?.channel!==channel||event.data?.type!=="connect"||!event.ports[0])return;port=event.ports[0];port.start()});addEventListener("keydown",event=>{if(!port||!event.isTrusted||!event.metaKey&&!event.ctrlKey)return;port.postMessage({channel,type:"keydown",key:event.key,code:event.code,metaKey:event.metaKey,ctrlKey:event.ctrlKey,shiftKey:event.shiftKey,altKey:event.altKey})})})();`
// Selection and highlight runtimes extend the shared canvas bridge.
const platformStylesheet = `
@import "tailwindcss";
@import "@posthog/quill/tokens.css";
@import "@posthog/quill/color-system.css";
@import "@posthog/quill/base.css";
@import "@posthog/quill/primitives.css";
@import "@posthog/quill/tailwind.css";
@custom-variant dark (&:where(.dark, .dark *));
`

// Entry references (module scripts, stylesheets) parsed attribute-order-
// insensitively: `<script src=... type="module">` is as valid as the reverse,
// so tags are matched first and their attributes read individually.
function entryReferences(html) {
    const references = []
    for (const tag of html.matchAll(htmlTag)) {
        const attributes = {}
        for (const attribute of tag[0].matchAll(htmlAttribute)) {
            attributes[attribute[1].toLowerCase()] = attribute[2] ?? attribute[3] ?? ''
        }
        if (tag[1].toLowerCase() === 'script' && attributes.type === 'module' && attributes.src) {
            references.push([attributes.src, 'js'])
        } else if (
            tag[1].toLowerCase() === 'link' &&
            attributes.rel === 'stylesheet' &&
            attributes.href &&
            !/^https:\/\//i.test(attributes.href)
        ) {
            // A remote HTTPS stylesheet is not a local build entry, so it stays
            // in the emitted HTML and loads at runtime under the declared-origin
            // style-src CSP. Only local stylesheets are bundled here.
            references.push([attributes.href, 'css'])
        }
    }
    return references
}

function diagnostic(code, message, file, line) {
    return {
        severity: 'error',
        code,
        message: String(message).slice(0, 10000),
        ...(file ? { path: file } : {}),
        ...(line ? { line } : {}),
    }
}

function sha256(content) {
    return createHash('sha256').update(content, 'utf8').digest('hex')
}

function normalize(value) {
    return value.replace(/^\.?\//, '')
}

function packageName(specifier) {
    return specifier.startsWith('@') ? specifier.split('/').slice(0, 2).join('/') : specifier.split('/')[0]
}

function resolveFile(files, importer, specifier) {
    const base = path.posix.normalize(path.posix.join(path.posix.dirname(importer), specifier))
    if (base.startsWith('..')) {
        return null
    }
    return extensions.map((extension) => base + extension).find((candidate) => candidate in files) ?? null
}

function loader(file) {
    const extension = path.posix.extname(file)
    return (
        {
            '.ts': 'ts',
            '.tsx': 'tsx',
            '.jsx': 'jsx',
            '.css': 'css',
            '.json': 'json',
            '.svg': 'dataurl',
            '.txt': 'text',
        }[extension] ?? 'js'
    )
}

function assetLoader(contentType) {
    return contentType === 'application/wasm' || contentType === 'application/octet-stream' ? 'binary' : 'dataurl'
}

function resolveStylesheet(id, base) {
    const resolved = id.startsWith('.')
        ? path.resolve(base, id)
        : builderRequire.resolve(id === 'tailwindcss' ? 'tailwindcss/index.css' : id)
    return {
        path: resolved,
        base: path.dirname(resolved),
        content: readFileSync(resolved, 'utf8'),
    }
}

async function buildPlatformStyles(project) {
    const compiler = await compile(platformStylesheet, {
        base: builderDirectory,
        loadStylesheet: resolveStylesheet,
    })
    const scanner = new Scanner({ sources: compiler.sources })
    const candidates = new Set(scanner.scan())
    const sourceFiles = Object.entries(project.files)
        .filter(([, content]) => typeof content === 'string')
        .map(([filename, content]) => ({
            content,
            extension: path.posix.extname(filename).slice(1) || 'html',
        }))
    for (const candidate of scanner.scanFiles(sourceFiles)) {
        candidates.add(candidate)
    }
    return compiler.build([...candidates])
}

function validate(project) {
    const diagnostics = []
    if (project.canvasSdkVersion !== '0.1.0') {
        diagnostics.push(diagnostic('unsupported_sdk', 'Canvas SDK version is unavailable'))
    }
    for (const [name, version] of Object.entries(project.dependencies ?? {})) {
        if (!admitted[name]) {
            diagnostics.push(diagnostic('dependency_not_admitted', `dependency "${name}" is not platform-supported`))
        } else if (admitted[name][0] !== version) {
            diagnostics.push(
                diagnostic('dependency_version_mismatch', `dependency "${name}" must use ${admitted[name][0]}`)
            )
        }
    }
    const html = project.files?.[project.entryHtml]
    if (typeof html !== 'string') {
        diagnostics.push(diagnostic('entry_not_found', 'Canvas entry HTML does not exist', project.entryHtml))
    } else if (forbiddenHtml.test(html)) {
        diagnostics.push(
            diagnostic('forbidden_url_scheme', 'Canvas HTML contains a forbidden URL scheme', project.entryHtml)
        )
    }
    return diagnostics
}

async function bundleEntry(project, entry) {
    const files = project.files
    const plugin = {
        name: 'canvas-virtual-fs',
        setup(pluginBuild) {
            pluginBuild.onResolve({ filter: /.*/ }, async (args) => {
                if (args.pluginData?.platformDependency) {
                    return undefined
                }
                if (args.kind === 'entry-point') {
                    return { path: normalize(args.path), namespace: 'canvas' }
                }
                if (!['canvas', 'canvas-worker'].includes(args.namespace)) {
                    return undefined
                }
                if (args.path.startsWith('.') || args.path.startsWith('/')) {
                    const workerImport = args.path.endsWith('?worker')
                    const requestedPath = workerImport ? args.path.slice(0, -7) : args.path
                    const specifier = requestedPath.startsWith('/') ? `./${normalize(requestedPath)}` : requestedPath
                    const resolved = resolveFile(files, args.importer, specifier)
                    if (resolved) {
                        return { path: resolved, namespace: workerImport ? 'canvas-worker' : 'canvas' }
                    }
                    const asset = resolveFile(project.assets ?? {}, args.importer, specifier)
                    return asset
                        ? { path: asset, namespace: 'canvas-asset' }
                        : { errors: [{ text: `cannot resolve "${args.path}"` }] }
                }
                const name = packageName(args.path)
                if (!Object.hasOwn(project.dependencies, name) || !Object.hasOwn(admitted, name)) {
                    return { errors: [{ text: `import_not_declared: "${args.path}"` }] }
                }
                if (args.path !== name && !Object.hasOwn(runtimeImports, args.path)) {
                    return { errors: [{ text: `import_not_declared: "${args.path}"` }] }
                }
                return pluginBuild.resolve(args.path, {
                    kind: args.kind,
                    resolveDir: builderDirectory,
                    pluginData: { platformDependency: true },
                })
            })
            pluginBuild.onLoad({ filter: /.*/, namespace: 'canvas' }, (args) => ({
                contents: files[args.path],
                loader: loader(args.path),
                resolveDir: '/',
            }))
            pluginBuild.onLoad({ filter: /.*/, namespace: 'canvas-asset' }, (args) => {
                const asset = project.assets?.[args.path]
                return asset
                    ? {
                          contents: Uint8Array.from(Buffer.from(asset.content, 'base64')),
                          loader: assetLoader(asset.contentType),
                      }
                    : null
            })
            pluginBuild.onLoad({ filter: /.*/, namespace: 'canvas-worker' }, async (args) => {
                const source = files[args.path]
                if (source === undefined) {
                    return null
                }
                const compiled = await bundleEntry(project, args.path)
                const code = (compiled.outputFiles ?? [])
                    .filter((output) => output.path.endsWith('.js'))
                    .map((output) => output.text)
                    .join('\n')
                return {
                    contents: `export default URL.createObjectURL(new Blob([${JSON.stringify(code)}],{type:"text/javascript"}));`,
                    loader: 'js',
                }
            })
        },
    }
    return build({
        entryPoints: [entry],
        bundle: true,
        write: false,
        format: 'esm',
        platform: 'browser',
        target: 'es2022',
        jsx: 'automatic',
        minify: true,
        sourcemap: false,
        logLevel: 'silent',
        outdir: 'out',
        plugins: [plugin],
    })
}

function artifact(pathname, content) {
    return { path: pathname, content, contentHash: sha256(content), sizeBytes: Buffer.byteLength(content, 'utf8') }
}

async function buildCanvas(project) {
    const diagnostics = validate(project)
    if (diagnostics.length) {
        return { contractVersion: 1, status: 'failed', diagnostics }
    }
    project = { ...project, files: { ...project.files }, dependencies: { ...project.dependencies } }
    let html = project.files[project.entryHtml]
    let legacy = null
    if (project.files['src/canvas.tsx'] && html.includes('src="/src/canvas.tsx"')) {
        legacy = { legacyComponentPath: 'src/canvas.tsx', legacyCode: project.files['src/canvas.tsx'] }
        project.files['src/canvas-entry.tsx'] =
            'import React from "react"; import { createRoot } from "react-dom/client"; import Canvas from "./canvas"; const root = document.getElementById("root"); if (root) createRoot(root).render(React.createElement(Canvas));'
        html = html.replace('src="/src/canvas.tsx"', 'src="/src/canvas-entry.tsx"')
        project.files[project.entryHtml] = html
        // The injected mount is platform code, not the author's — admit the react/
        // react-dom it needs even when the source only declared react.
        for (const runtime of ['react', 'react-dom']) {
            project.dependencies[runtime] ??= admitted[runtime][0]
        }
    }
    const refs = entryReferences(html)
    if (!refs.length) {
        return {
            contractVersion: 1,
            status: 'failed',
            diagnostics: [
                diagnostic(
                    'no_entry_module',
                    'Canvas HTML references no module scripts or stylesheets',
                    project.entryHtml
                ),
            ],
        }
    }
    const files = []
    let platformCss = ''
    try {
        for (const [reference, kind] of refs) {
            const entry = normalize(reference)
            if (!(entry in project.files)) {
                return {
                    contractVersion: 1,
                    status: 'failed',
                    diagnostics: [
                        diagnostic('entry_not_found', `Canvas entry ${entry} does not exist`, project.entryHtml),
                    ],
                }
            }
            const result = await bundleEntry(project, entry)
            let javascript = ''
            let css = ''
            for (const output of result.outputFiles ?? []) {
                output.path.endsWith('.css') ? (css = output.text) : (javascript = output.text)
            }
            const content = kind === 'css' ? css : javascript
            const emitted = `assets/${path.posix.basename(entry).replace(/\.[^.]+$/, '')}-${sha256(content).slice(0, 10)}.${kind}`
            files.push(artifact(emitted, content))
            html = html.split(`"${reference}"`).join(`"./${emitted}"`).split(`'${reference}'`).join(`'./${emitted}'`)
            if (kind === 'js' && css) {
                const cssPath = `assets/${path.posix.basename(entry).replace(/\.[^.]+$/, '')}-${sha256(css).slice(0, 10)}.css`
                files.push(artifact(cssPath, css))
                const stylesheet = `<link rel="stylesheet" href="./${cssPath}" />`
                html = html.includes('</head>')
                    ? html.replace('</head>', `${stylesheet}</head>`)
                    : `${stylesheet}${html}`
            }
        }
        platformCss = await buildPlatformStyles(project)
    } catch (error) {
        const errors = error?.errors ?? []
        return {
            contractVersion: 1,
            status: 'failed',
            diagnostics: errors.length
                ? errors
                      .slice(0, 500)
                      .map((entry) =>
                          diagnostic(
                              entry.text.startsWith('import_not_declared:') ? 'import_not_declared' : 'bundle_error',
                              entry.text,
                              entry.location?.file?.replace(/^canvas:/, ''),
                              entry.location?.line
                          )
                      )
                : [diagnostic('bundle_error', error instanceof Error ? error.message : String(error))],
        }
    }
    const cssPath = `assets/canvas-platform-${sha256(platformCss).slice(0, 10)}.css`
    files.push(artifact(cssPath, platformCss))
    files.push(artifact(runtimePath, `${runtime}\n${selectionRuntime}\n${highlightRuntime}\n${keyboardRuntime}`))
    const networkOrigins = project.capabilities?.network?.origins ?? []
    const externalSources = networkOrigins.join(' ')
    const projectCsp = externalSources
        ? csp
              .replace("connect-src 'none'", `connect-src ${externalSources}`)
              .replace("style-src 'self' 'unsafe-inline'", `style-src 'self' 'unsafe-inline' ${externalSources}`)
              .replace("img-src 'self' data: blob:", `img-src 'self' data: blob: ${externalSources}`)
              .replace("font-src 'self' data:", `font-src 'self' data: ${externalSources}`)
              .replace("media-src 'self' data: blob:", `media-src 'self' data: blob: ${externalSources}`)
              .replace("frame-src 'none'", `frame-src ${externalSources}`)
        : csp
    const head = `<meta http-equiv="Content-Security-Policy" content="${projectCsp}" /><link rel="stylesheet" href="./${cssPath}" /><script src="./${runtimePath}"></script>`
    html = html.includes('<head>') ? html.replace('<head>', `<head>${head}`) : `${head}${html}`
    files.unshift(artifact(project.entryHtml, html))
    const manifest = {
        entryHtml: project.entryHtml,
        assets: files.map(({ path, contentHash, sizeBytes }) => ({ path, contentHash, sizeBytes })),
        dependencies: project.dependencies,
        canvasSdkVersion: project.canvasSdkVersion,
        capabilities: project.capabilities ?? {
            posthog: { insights: [], inlineQueries: false, captureEvents: [] },
            network: { origins: [] },
        },
        // Component-kind canvases freeze their placement contract (size,
        // config schema) into the artifact, like capabilities: the grid host
        // holds a placed widget to the contract its build shipped with.
        ...(project.component ? { component: project.component } : {}),
        ...legacy,
    }
    return { contractVersion: 1, status: 'ready', diagnostics: [], manifest, files }
}

let input = ''
for await (const chunk of process.stdin) {
    input += chunk
}
try {
    const request = JSON.parse(input)
    process.stdout.write(JSON.stringify(await buildCanvas(request.project)))
} catch (error) {
    process.stdout.write(
        JSON.stringify({
            contractVersion: 1,
            status: 'failed',
            diagnostics: [diagnostic('invalid_build_request', error instanceof Error ? error.message : String(error))],
        })
    )
}
