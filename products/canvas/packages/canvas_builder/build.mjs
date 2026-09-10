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
// Platform-provided, so it is inlined here rather than admitted as a pinned
// dependency; the preview sandbox serves the same source from a blob.
const canvasSdkSpecifier = '@posthog/canvas-sdk'
const canvasSdkModule = readFileSync(new URL('./canvas-sdk.mjs', import.meta.url), 'utf8')
// Progressive fragments: the layout owns one instance of every shared module
// and publishes it on globalThis; each fragment chunk reads those instances
// through a shim instead of bundling its own copy. The marker component is a
// builder-provided module compiled in the author namespace so `react` resolves
// against the declared dependency. Without a registry (a build without
// progressive fragments, or the preview document) every marker renders its
// fallback.
const fragmentSdkSpecifier = '@posthog/canvas-sdk/fragment'
const fragmentSdkModule = `import React, { useEffect, useState } from 'react'
const registry = globalThis.__posthogCanvasFragments ?? { base: '', fragments: {}, subscribe: () => () => {}, report() {}, error() {} }
export function CanvasFragment({ path, fallback = null, props }) {
    const [entry, setEntry] = useState(() => registry.fragments[path])
    useEffect(() => registry.subscribe(() => setEntry(registry.fragments[path])), [path])
    const [Loaded, setLoaded] = useState(null)
    useEffect(() => {
        if (!entry) {
            setLoaded(null)
            return
        }
        let live = true
        import(new URL(entry.file, registry.base).href)
            .then((m) => {
                if (live) {
                    setLoaded(() => m.default)
                    registry.report(path)
                }
            })
            .catch((error) => registry.error(path, error))
        return () => {
            live = false
        }
    // Keyed on the content hash, not the URL: every build serves the chunk from
    // its own base, so an unchanged fragment must keep its mounted component.
    }, [path, entry?.contentHash])
    if (!Loaded) return fallback
    return <Loaded {...(props ?? {})} />
}
`
const sharedDirectory = 'src/shared/'
const fragmentsDirectory = 'src/fragments/'
const codeExtensions = ['.ts', '.tsx', '.js', '.jsx']
const fragmentMarker = /<CanvasFragment\b[^>]*\bpath\s*=\s*["']([^"']+)["']/g
const builderDirectory = path.dirname(fileURLToPath(import.meta.url))
const builderRequire = createRequire(import.meta.url)
const htmlTag = /<(script|link)\b(?:[^>"']|"[^"]*"|'[^']*')*>/gi
const htmlAttribute = /([a-zA-Z][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g
const forbiddenHtml = /(?:src|href)\s*=\s*["']\s*(javascript|data:text\/html|vbscript)/i
const extensions = ['', '.ts', '.tsx', '.js', '.jsx', '.css', '.json', '.svg', '.txt']
const runtimePath = 'assets/canvas-runtime.js'
const notebookFrameKeyPrefix = '__posthog_notebook_frame__:'
// The host only delivers the MessagePort after the artifact iframe's load
// event, which fires after the app's module scripts have already run, so any
// ph.* call issued during mount lands before the port exists. Those messages
// queue (bounded, in case the host never connects) and flush on connect.
const runtime = `(()=>{const channel="posthog-canvas",pending=new Map,queued=[];let sequence=0,port;const post=(message)=>{const payload={channel,...message};if(port){port.postMessage(payload)}else if(queued.length<256){queued.push(payload)}};const call=(method,payload)=>new Promise((resolve,reject)=>{if(!port&&(method==="actionInvoke"||method==="agentRequest")){reject(new Error("Canvas actions require a user action"));return}const id=String(++sequence);const timer=setTimeout(()=>{pending.delete(id);const queuedIndex=queued.findIndex((message)=>message.type==="data-request"&&message.id===id);if(queuedIndex>-1)queued.splice(queuedIndex,1);reject(new Error("Canvas request timed out"));},30000);pending.set(id,{resolve,reject,timer});post({type:"data-request",id,method,payload});});const applyTheme=(theme)=>{if(theme!=="dark"&&theme!=="light")return;const dark=theme==="dark";document.documentElement.classList.toggle("dark",dark);document.documentElement.style.colorScheme=dark?"dark":"light";};const fragmentParams=new URLSearchParams(location.hash.slice(1));applyTheme(fragmentParams.get("theme"));let config={};try{const rawConfig=fragmentParams.get("config");if(rawConfig)config=Object.freeze(JSON.parse(rawConfig))}catch{config={}};const receive=(event)=>{if(event.data?.channel!==channel)return;if(event.data.type==="set-theme"){applyTheme(event.data.theme);return}if(event.data.type!=="data-response")return;const request=pending.get(event.data.id);if(!request)return;pending.delete(event.data.id);clearTimeout(request.timer);event.data.ok?request.resolve(event.data.result):request.reject(new Error(event.data.error??"Canvas request failed"));};const capture=(event,properties,distinctId)=>{const normalized=properties??{};let serialized;try{serialized=JSON.stringify(normalized)}catch{throw new Error("Canvas capture properties must be serializable")};if(typeof serialized!=="string"||serialized.length>16384)throw new Error("Canvas capture properties are too large");return call("capture",{event,properties:normalized,distinctId})};const openExternal=(value)=>{const url=new URL(value);if(url.protocol!=="https:"||!(url.hostname==="posthog.com"||url.hostname.endsWith(".posthog.com")))throw new Error("Canvas external URL is not allowed");post({type:"open-external",url:url.href})};window.ph={config,loadInsight:(shortId,options)=>call("loadInsight",{shortId,dateRange:options?.dateRange,variables:options?.variables,refresh:options?.refresh}),query:(query,params,options)=>call("query",typeof query==="string"?{hogql:query,params:params??{},refresh:options?.refresh}:{query,params:params??{},refresh:options?.refresh}),capture,openExternal,agent:{request:(prompt)=>call("agentRequest",{prompt})},state:{get:(key,opts)=>call("stateGet",{key,scope:opts?.scope||"user"}),set:(key,value,opts)=>call("stateSet",{key,value:value===undefined?null:value,scope:opts?.scope||"user"}),list:(opts)=>call("stateList",{scope:opts?.scope})},actions:{invoke:(verb,payload)=>call("actionInvoke",{verb,payload:payload??{}})},connectors:{call:(provider,tool,args,options)=>call("connectorCall",{provider,tool,arguments:args??{},refresh:options?.refresh}),connect:(provider)=>{if(!navigator.userActivation?.isActive)throw new Error("Connecting a provider requires a user action");post({type:"navigate",nav:{target:"connect",provider}})}}};addEventListener("message",(event)=>{if(port||event.source!==parent||event.data?.channel!==channel||event.data?.type!=="connect"||!event.ports[0])return;port=event.ports[0];port.addEventListener("message",receive);port.start();while(queued.length)port.postMessage(queued.shift());if(document.readyState!=="loading")post({type:"ready"});if(document.readyState==="complete")post({type:"rendered"});});addEventListener("error",(event)=>post({type:"error",message:event.message||"Canvas runtime error",stack:event.error?.stack}));addEventListener("unhandledrejection",(event)=>post({type:"error",message:event.reason instanceof Error?event.reason.message:String(event.reason),stack:event.reason instanceof Error?event.reason.stack:undefined}));const cspSeen=new Set();addEventListener("securitypolicyviolation",(event)=>{const directive=event.effectiveDirective||"unknown";if(cspSeen.has(directive))return;cspSeen.add(directive);post({type:"error",message:"SecurityPolicyViolationError: "+directive})});addEventListener("DOMContentLoaded",()=>post({type:"ready"}));addEventListener("load",()=>post({type:"rendered"}));})();`
// Notebook source remains arbitrary JavaScript, and its separate AI review is advisory.
// The cross-origin sandbox, CSP, host authorization, and frame allow-list are
// load-bearing controls. Navigation interception is defense in depth: the Navigation
// API covers Chromium, while click, submit, and window.open guards reduce accidental
// navigation in other browsers.
const notebookRuntime = (allowedFrameNames) =>
    `(()=>{const channel="posthog-canvas",bridge=new MessageChannel,allowedFrames=new Set(${JSON.stringify(allowedFrameNames)}),stateGet=ph.state.get;delete ph.state;dispatchEvent(new MessageEvent("message",{data:{channel,type:"connect"},source:parent,ports:[bridge.port1]}));parent.postMessage({channel,type:"notebook-connect"},"*",[bridge.port2]);const preventDefault=Event.prototype.preventDefault;const blockNavigation=event=>preventDefault.call(event);globalThis.navigation?.addEventListener("navigate",blockNavigation);globalThis.addEventListener("click",event=>{if(event.target instanceof Element&&event.target.closest("a"))blockNavigation(event)},true);globalThis.addEventListener("submit",blockNavigation,true);Object.defineProperty(globalThis,"open",{value:()=>null,writable:false,configurable:false});Object.defineProperty(ph,"readFrame",{value:(name,options={})=>{if(typeof name!=="string"||!allowedFrames.has(name))throw new Error("Notebook dataframe is not available");return stateGet(${JSON.stringify(notebookFrameKeyPrefix)}+encodeURIComponent(name)+":"+(options.offset??0)+":"+(options.limit??100),{scope:"user"})},writable:false,configurable:false});})();`
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
// The fragment registry is baked per build: the host swaps in a newer build's
// fragments over the port when the layout hash still matches, so the mounted
// document keeps its state while fragment chunks (and the platform stylesheet
// that scanned them) roll forward.
const fragmentsRuntime = (fragments) =>
    `(()=>{const channel="posthog-canvas",queued=[];let port;const post=message=>{const payload={channel,...message};if(port)port.postMessage(payload);else if(queued.length<256)queued.push(payload)};const registry={base:document.baseURI,fragments:${JSON.stringify(fragments)},listeners:new Set,subscribe(listener){registry.listeners.add(listener);return()=>registry.listeners.delete(listener)},report(path){post({type:"fragment-rendered",path})},error(path,error){post({type:"error",message:"Fragment "+path+": "+(error instanceof Error?error.message:String(error)),stack:error instanceof Error?error.stack:undefined})}};globalThis.__posthogCanvasFragments=registry;const swapStylesheet=href=>{const current=document.querySelector('link[rel="stylesheet"][href*="canvas-platform-"]');if(current&&current.href===href)return;const link=document.createElement("link");link.rel="stylesheet";link.href=href;if(current){link.addEventListener("load",()=>current.remove());current.after(link)}else document.head.appendChild(link)};const apply=({base,fragments,platformCss})=>{const next={};for(const [path,entry] of Object.entries(fragments??{})){if(entry&&typeof entry.file==="string")next[path]={file:new URL(entry.file,base).href,contentHash:entry.contentHash}}registry.fragments=next;if(typeof platformCss==="string")swapStylesheet(new URL(platformCss,base).href);for(const listener of registry.listeners)listener()};addEventListener("message",event=>{if(port||event.source!==parent||event.data?.channel!==channel||event.data?.type!=="connect"||!event.ports[0])return;port=event.ports[0];port.addEventListener("message",event=>{if(event.data?.channel===channel&&event.data?.type==="set-fragments")apply(event.data)});port.start();while(queued.length)port.postMessage(queued.shift())})})();`
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
            const quote = attribute[2] !== undefined ? '"' : "'"
            attributes[attribute[1].toLowerCase()] = {
                value: attribute[2] ?? attribute[3] ?? '',
                valueStart: tag.index + attribute.index + attribute[0].indexOf(quote) + 1,
            }
        }
        let entry
        let kind
        if (tag[1].toLowerCase() === 'script' && attributes.type?.value === 'module' && attributes.src?.value) {
            entry = attributes.src
            kind = 'js'
        } else if (
            tag[1].toLowerCase() === 'link' &&
            attributes.rel?.value === 'stylesheet' &&
            attributes.href?.value &&
            !/^https:\/\//i.test(attributes.href.value)
        ) {
            // A remote HTTPS stylesheet is not a local build entry, so it stays
            // in the emitted HTML and loads at runtime under the declared-origin
            // style-src CSP. Only local stylesheets are bundled here.
            entry = attributes.href
            kind = 'css'
        } else {
            continue
        }
        references.push({ reference: entry.value, kind, valueStart: entry.valueStart })
    }
    return references
}

function rewriteEntryReferences(html, reference, replacement, kind) {
    for (const entry of entryReferences(html).reverse()) {
        if (entry.reference === reference && entry.kind === kind) {
            html = html.slice(0, entry.valueStart) + replacement + html.slice(entry.valueStart + reference.length)
        }
    }
    return html
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
    // Sources persist the SDK version they were authored against, so every
    // version ever scaffolded must keep building, so the list only grows.
    if (!contract.supportedSdkVersions.includes(project.canvasSdkVersion)) {
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

// `shared` is the set of module keys a fragment chunk must read from the layout
// instead of bundling (null for the layout build itself). The shim is CommonJS
// on purpose: esbuild binds CommonJS exports at runtime, so no export list is
// needed and CommonJS platform packages (react, react-dom) work like the ESM
// ones. The layout marks each published namespace `__esModule` so a fragment's
// default import reads the module's default export, not the namespace.
function virtualFsPlugin(project, shared) {
    const files = project.files
    const reactDeclared = Object.hasOwn(project.dependencies, 'react')
    return {
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
                if (shared?.has(args.path)) {
                    return { path: args.path, namespace: 'canvas-shared' }
                }
                if (args.path === canvasSdkSpecifier) {
                    return { path: canvasSdkSpecifier, namespace: 'canvas-sdk' }
                }
                if (args.path === fragmentSdkSpecifier) {
                    return reactDeclared
                        ? { path: fragmentSdkSpecifier, namespace: 'canvas' }
                        : { errors: [{ text: `import_not_declared: "${args.path}"` }] }
                }
                if (args.path.startsWith('.') || args.path.startsWith('/')) {
                    const workerImport = args.path.endsWith('?worker')
                    const requestedPath = workerImport ? args.path.slice(0, -7) : args.path
                    const specifier = requestedPath.startsWith('/') ? `./${normalize(requestedPath)}` : requestedPath
                    const resolved = resolveFile(files, args.importer, specifier)
                    if (resolved && shared) {
                        if (shared.has(`./${resolved}`)) {
                            return { path: `./${resolved}`, namespace: 'canvas-shared' }
                        }
                        if (resolved.startsWith(fragmentsDirectory) && args.importer.startsWith(fragmentsDirectory)) {
                            return {
                                errors: [
                                    {
                                        text: `fragment_imports_fragment: "${args.path}" is a fragment; import shared code from src/shared/ instead`,
                                    },
                                ],
                            }
                        }
                    }
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
            pluginBuild.onLoad({ filter: /.*/, namespace: 'canvas-sdk' }, () => ({
                contents: canvasSdkModule,
                loader: 'js',
            }))
            pluginBuild.onLoad({ filter: /.*/, namespace: 'canvas-shared' }, (args) => ({
                contents: `const m=globalThis.__posthogCanvasModules?.[${JSON.stringify(args.path)}];if(!m)throw new Error(${JSON.stringify(`Canvas shared module ${args.path} is not loaded`)});module.exports=m`,
                loader: 'js',
            }))
            pluginBuild.onLoad({ filter: /.*/, namespace: 'canvas' }, (args) =>
                args.path === fragmentSdkSpecifier
                    ? { contents: fragmentSdkModule, loader: 'tsx', resolveDir: '/' }
                    : { contents: files[args.path], loader: loader(args.path), resolveDir: '/' }
            )
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
}

const bundleOptions = {
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
}

async function bundleEntry(project, entry) {
    return build({ ...bundleOptions, entryPoints: [entry], plugins: [virtualFsPlugin(project, null)] })
}

function artifact(pathname, content) {
    return { path: pathname, content, contentHash: sha256(content), sizeBytes: Buffer.byteLength(content, 'utf8') }
}

function isCodeFile(file) {
    return codeExtensions.includes(path.posix.extname(file))
}

// Manifest key of a fragment file: its path under src/ without the extension.
function fragmentKey(file) {
    return file.slice('src/'.length).replace(/\.[^./]+$/, '')
}

function relativeImport(fromDirectory, file) {
    const relative = path.posix.relative(fromDirectory, file)
    return relative.startsWith('.') ? relative : `./${relative}`
}

// Module keys a fragment reads from the layout: every declared platform
// dependency (and its runtime entries), the SDK modules, and every shared file.
function sharedModuleKeys(project, sharedFiles) {
    const keys = [canvasSdkSpecifier]
    for (const name of Object.keys(project.dependencies)) {
        keys.push(name)
        for (const runtimeImport of Object.keys(runtimeImports)) {
            if (packageName(runtimeImport) === name) {
                keys.push(runtimeImport)
            }
        }
    }
    if (Object.hasOwn(project.dependencies, 'react')) {
        keys.push(fragmentSdkSpecifier)
    }
    for (const file of sharedFiles) {
        keys.push(`./${file}`)
    }
    return keys
}

// The layout entry is wrapped so the shared module instances it bundles are
// published before any fragment chunk loads. Imports keep the original entry's
// evaluation order relative to the shared modules; the body runs after both.
function layoutWrapperModule(wrapperPath, entry, keys) {
    const directory = path.posix.dirname(wrapperPath)
    const specifier = (key) => (key.startsWith('./') ? relativeImport(directory, key.slice(2)) : key)
    const imports = keys.map((key, index) => `import * as m${index} from ${JSON.stringify(specifier(key))}`)
    const entries = keys.map((key, index) => `${JSON.stringify(key)}:share(m${index})`)
    return [
        ...imports,
        `import ${JSON.stringify(relativeImport(directory, entry))}`,
        'const share = (m) => { const o = {}; for (const k of Object.keys(m)) Object.defineProperty(o, k, { get: () => m[k], enumerable: true }); Object.defineProperty(o, "__esModule", { value: true }); return o }',
        `globalThis.__posthogCanvasModules = {${entries.join(',')}}`,
    ].join('\n')
}

async function bundleFragments(project, fragmentFiles, shared) {
    const result = await build({
        ...bundleOptions,
        entryPoints: fragmentFiles.map((file) => ({ in: file, out: fragmentKey(file) })),
        metafile: true,
        plugins: [virtualFsPlugin(project, shared)],
    })
    const outputs = new Map(
        (result.outputFiles ?? []).map((output) => [path.relative(process.cwd(), output.path), output.text])
    )
    const fragments = {}
    const files = []
    for (const [outputPath, meta] of Object.entries(result.metafile.outputs)) {
        if (!meta.entryPoint || !outputPath.endsWith('.js')) {
            continue
        }
        const key = fragmentKey(meta.entryPoint.replace(/^canvas:/, ''))
        const content = outputs.get(outputPath) ?? ''
        const emitted = `${key}-${sha256(content).slice(0, 10)}.js`
        const file = artifact(emitted, content)
        files.push(file)
        fragments[key] = { file: emitted, contentHash: file.contentHash }
    }
    return { fragments, files }
}

function scanFragmentMarkers(files) {
    const markers = new Set()
    for (const content of Object.values(files)) {
        if (typeof content !== 'string') {
            continue
        }
        for (const match of content.matchAll(fragmentMarker)) {
            markers.add(match[1])
        }
    }
    return [...markers].sort()
}

function failed(...diagnostics) {
    return { contractVersion: 1, status: 'failed', diagnostics }
}

// Splits the project into layout, shared, and fragment inputs, and injects the
// layout wrapper. Returns diagnostics when the fragment set is unusable.
function prepareFragments(project, html) {
    const sharedFiles = Object.keys(project.files)
        .filter((file) => file.startsWith(sharedDirectory) && isCodeFile(file))
        .sort()
    const fragmentFiles = Object.keys(project.files)
        .filter((file) => file.startsWith(fragmentsDirectory) && isCodeFile(file))
        .sort()
    if (fragmentFiles.length > contract.limits.maxFragments) {
        return {
            diagnostics: [
                diagnostic('too_many_fragments', `a canvas may contain at most ${contract.limits.maxFragments} fragments`),
            ],
        }
    }
    const keys = new Set(fragmentFiles.map(fragmentKey))
    if (keys.size !== fragmentFiles.length) {
        return {
            diagnostics: [
                diagnostic('duplicate_fragment', 'two fragment files share a name and differ only by extension'),
            ],
        }
    }
    const layoutReference = entryReferences(html).find(({ kind }) => kind === 'js')
    if (!layoutReference) {
        return { diagnostics: [diagnostic('no_entry_module', 'Canvas HTML references no module script', project.entryHtml)] }
    }
    const entry = normalize(layoutReference.reference)
    if (!(entry in project.files)) {
        return { diagnostics: [diagnostic('entry_not_found', `Canvas entry ${entry} does not exist`, project.entryHtml)] }
    }
    const wrapperPath = path.posix.join(path.posix.dirname(entry), 'canvas-layout-entry.tsx')
    if (wrapperPath in project.files) {
        return { diagnostics: [diagnostic('reserved_path', `${wrapperPath} is reserved for the canvas builder`, wrapperPath)] }
    }
    const shared = sharedModuleKeys(project, sharedFiles)
    project.files[wrapperPath] = layoutWrapperModule(wrapperPath, entry, shared)
    return {
        html: rewriteEntryReferences(html, layoutReference.reference, `/${wrapperPath}`, 'js'),
        wrapperPath,
        fragmentFiles,
        shared: new Set(shared),
    }
}

const builderErrorCodes = new Set(['import_not_declared', 'fragment_imports_fragment'])

function bundleFailure(error) {
    const errors = error?.errors ?? []
    return failed(
        ...(errors.length
            ? errors.slice(0, 500).map((entry) => {
                  const code = entry.text.match(/^([a-z_]+): /)?.[1]
                  return diagnostic(
                      builderErrorCodes.has(code) ? code : 'bundle_error',
                      entry.text,
                      entry.location?.file?.replace(/^canvas:/, ''),
                      entry.location?.line
                  )
              })
            : [diagnostic('bundle_error', error instanceof Error ? error.message : String(error))])
    )
}

async function buildCanvas(project) {
    const diagnostics = validate(project)
    if (diagnostics.length) {
        return failed(...diagnostics)
    }
    project = { ...project, files: { ...project.files }, dependencies: { ...project.dependencies } }
    let html = project.files[project.entryHtml]
    let legacy = null
    if (
        project.files['src/canvas.tsx'] &&
        entryReferences(html).some(({ reference, kind }) => reference === '/src/canvas.tsx' && kind === 'js')
    ) {
        legacy = { legacyComponentPath: 'src/canvas.tsx', legacyCode: project.files['src/canvas.tsx'] }
        project.files['src/canvas-entry.tsx'] =
            'import React from "react"; import { createRoot } from "react-dom/client"; import Canvas from "./canvas"; const root = document.getElementById("root"); if (root) createRoot(root).render(React.createElement(Canvas));'
        html = rewriteEntryReferences(html, '/src/canvas.tsx', '/src/canvas-entry.tsx', 'js')
        project.files[project.entryHtml] = html
        // The injected mount is platform code, not the author's — admit the react/
        // react-dom it needs even when the source only declared react.
        for (const runtime of ['react', 'react-dom']) {
            project.dependencies[runtime] ??= admitted[runtime][0]
        }
    }
    let refs = entryReferences(html)
    if (!refs.length) {
        return failed(
            diagnostic('no_entry_module', 'Canvas HTML references no module scripts or stylesheets', project.entryHtml)
        )
    }
    let progressive = null
    if (project.progressiveFragments === true) {
        progressive = prepareFragments(project, html)
        if (progressive.diagnostics) {
            return failed(...progressive.diagnostics)
        }
        html = progressive.html
        project.files[project.entryHtml] = html
        refs = entryReferences(html)
    }
    const files = []
    let platformCss = ''
    let fragmentsBuild = null
    let layoutHash
    try {
        for (const { reference, kind } of refs) {
            const entry = normalize(reference)
            if (!(entry in project.files)) {
                return failed(diagnostic('entry_not_found', `Canvas entry ${entry} does not exist`, project.entryHtml))
            }
            const result = await bundleEntry(project, entry)
            let javascript = ''
            let css = ''
            for (const output of result.outputFiles ?? []) {
                output.path.endsWith('.css') ? (css = output.text) : (javascript = output.text)
            }
            const content = kind === 'css' ? css : javascript
            const emitted = `assets/${path.posix.basename(entry).replace(/\.[^.]+$/, '')}-${sha256(content).slice(0, 10)}.${kind}`
            const layout = artifact(emitted, content)
            files.push(layout)
            if (entry === progressive?.wrapperPath) {
                layoutHash = layout.contentHash
            }
            html = rewriteEntryReferences(html, reference, `./${emitted}`, kind)
            if (kind === 'js' && css) {
                const cssPath = `assets/${path.posix.basename(entry).replace(/\.[^.]+$/, '')}-${sha256(css).slice(0, 10)}.css`
                files.push(artifact(cssPath, css))
                const stylesheet = `<link rel="stylesheet" href="./${cssPath}" />`
                html = html.includes('</head>')
                    ? html.replace('</head>', `${stylesheet}</head>`)
                    : `${stylesheet}${html}`
            }
        }
        if (progressive) {
            fragmentsBuild = await bundleFragments(project, progressive.fragmentFiles, progressive.shared)
            files.push(...fragmentsBuild.files)
        }
        platformCss = await buildPlatformStyles(project)
    } catch (error) {
        return bundleFailure(error)
    }
    const cssPath = `assets/canvas-platform-${sha256(platformCss).slice(0, 10)}.css`
    files.push(artifact(cssPath, platformCss))
    const allowedNotebookFrames = project.capabilities?.posthog?.notebookFrames
    const notebookBridge = Array.isArray(allowedNotebookFrames) ? `\n${notebookRuntime(allowedNotebookFrames)}` : ''
    const fragmentsBridge = fragmentsBuild ? `\n${fragmentsRuntime(fragmentsBuild.fragments)}` : ''
    files.push(
        artifact(
            runtimePath,
            `${runtime}${notebookBridge}\n${selectionRuntime}\n${highlightRuntime}\n${keyboardRuntime}${fragmentsBridge}`
        )
    )
    let fragmentsManifest = {}
    if (fragmentsBuild) {
        const markers = scanFragmentMarkers(project.files)
        fragmentsManifest = {
            fragments: fragmentsBuild.fragments,
            markers,
            pendingFragments: markers.filter((marker) => !Object.hasOwn(fragmentsBuild.fragments, marker)),
            layoutHash,
            platformCss: cssPath,
        }
    }
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
    // `sandbox` is ignored in a <meta> policy and logs a console warning on every
    // artifact load; the artifact origin delivers it via the response header.
    const metaCsp = projectCsp.replace(/^sandbox[^;]*;\s*/, '')
    const head = `<meta http-equiv="Content-Security-Policy" content="${metaCsp}" /><link rel="stylesheet" href="./${cssPath}" /><script src="./${runtimePath}"></script>`
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
        ...fragmentsManifest,
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
