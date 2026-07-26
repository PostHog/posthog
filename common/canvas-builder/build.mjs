import { build } from 'esbuild'
import { createHash } from 'node:crypto'
import { builtinModules, createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const admittedDependencies = new Map([
    ['@posthog/quill', '0.3.0-beta.24'],
    ['react', '19.2.6'],
    ['react-dom', '19.2.6'],
    ['three', '0.183.2'],
])
const nodeBuiltins = new Set([...builtinModules, ...builtinModules.map((name) => `node:${name}`)])
const sourceExtensions = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.css', '.json']
const moduleScript = /<script\b(?=[^>]*\btype=["']module["'])(?=[^>]*\bsrc=["']([^"']+)["'])[^>]*>\s*<\/script>/gi
const remoteScript = /<script\b[^>]*\bsrc=["'](?:https?:)?\/\/[^"']+["'][^>]*>/i
const inlineScript = /<script\b(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/i
const inlineEventHandler = /\son[a-z]+\s*=/i
const javascriptUrl = /\b(?:href|src)\s*=\s*["']\s*javascript:/i
const runtimePath = 'assets/canvas-runtime.js'
const runtime = `(()=>{const channel="posthog-canvas",pending=new Map;let sequence=0;const post=(message)=>parent.postMessage({channel,...message},"*");const call=(method,payload)=>new Promise((resolve,reject)=>{const id=String(++sequence);pending.set(id,{resolve,reject});post({type:"data-request",id,method,payload});});window.ph={loadInsight:(shortId,options)=>call("loadInsight",{shortId,dateRange:options?.dateRange}),query:(query,params)=>call("query",typeof query==="string"?{hogql:query,params:params??{}}:{query,params:params??{}}),capture:(event,properties,distinctId)=>call("capture",{event,properties:properties??{},distinctId}),openExternal:(url)=>post({type:"open-external",url}),navigate:{toTask:(taskId)=>post({type:"navigate",nav:{target:"task",taskId}}),toNewTask:()=>post({type:"navigate",nav:{target:"new-task"}}),toCanvas:(dashboardId)=>post({type:"navigate",nav:{target:"canvas",dashboardId}}),toNewCanvas:()=>post({type:"navigate",nav:{target:"new-canvas"}})}};addEventListener("message",(event)=>{if(event.source!==parent||event.data?.channel!==channel||event.data?.type!=="data-response")return;const request=pending.get(event.data.id);if(!request)return;pending.delete(event.data.id);event.data.ok?request.resolve(event.data.result):request.reject(new Error(event.data.error??"Canvas request failed"));});addEventListener("click",(event)=>{const anchor=event.target instanceof Element?event.target.closest("a[href]"):null;if(!anchor)return;event.preventDefault();const url=anchor.href;if(url)post({type:"open-external",url});});addEventListener("error",(event)=>post({type:"error",message:event.message||"Canvas runtime error",stack:event.error?.stack}));addEventListener("unhandledrejection",(event)=>post({type:"error",message:event.reason instanceof Error?event.reason.message:String(event.reason),stack:event.reason instanceof Error?event.reason.stack:undefined}));addEventListener("DOMContentLoaded",()=>post({type:"ready"}));addEventListener("load",()=>post({type:"rendered"}));})();`

function diagnostic(code, message, file, location = {}) {
    return { severity: 'error', code, message: String(message).slice(0, 10000), ...(file ? { file } : {}), ...location }
}

function packageName(specifier) {
    return specifier.startsWith('@') ? specifier.split('/').slice(0, 2).join('/') : specifier.split('/')[0]
}

function normalizeProjectPath(filePath) {
    return path.posix.normalize(filePath.replace(/^\/+/, ''))
}

function loaderFor(filePath) {
    const extension = path.posix.extname(filePath)
    if (extension === '.ts') return 'ts'
    if (extension === '.tsx') return 'tsx'
    if (extension === '.jsx') return 'jsx'
    if (extension === '.css') return 'css'
    if (extension === '.json') return 'json'
    return 'js'
}

function resolveProjectFile(files, importer, specifier) {
    const candidate = specifier.startsWith('/')
        ? normalizeProjectPath(specifier)
        : normalizeProjectPath(path.posix.join(path.posix.dirname(importer), specifier))
    return [
        candidate,
        ...sourceExtensions.map((extension) => `${candidate}${extension}`),
        ...sourceExtensions.map((extension) => path.posix.join(candidate, `index${extension}`)),
    ].find((entry) => entry in files)
}

function importSpecifiers(source) {
    const pattern =
        /(?:\bimport\s*(?:[^"']*?\sfrom\s*)?|\bexport\s+[^"']*?\sfrom\s*|\brequire\s*\()\s*["']([^"']+)["']/g
    return [...source.matchAll(pattern)].map((match) => match[1]).filter(Boolean)
}

function validateProject(project) {
    const diagnostics = []
    if (project.canvasSdkVersion !== '1.0.0')
        diagnostics.push(diagnostic('unsupported_sdk', `Canvas SDK version ${project.canvasSdkVersion} is unavailable`))
    const imported = new Map()
    for (const [file, source] of Object.entries(project.files)) {
        for (const specifier of importSpecifiers(source)) {
            if (specifier.startsWith('.') || specifier.startsWith('/')) continue
            const name = packageName(specifier)
            if (
                nodeBuiltins.has(specifier) ||
                nodeBuiltins.has(name) ||
                specifier.includes('\\') ||
                specifier.split('/').includes('..')
            ) {
                diagnostics.push(
                    diagnostic(
                        'forbidden_import',
                        `Node built-in import "${specifier}" is unavailable in canvases`,
                        file
                    )
                )
                continue
            }
            imported.set(name, file)
        }
    }
    for (const [name, file] of imported) {
        if (!project.dependencies[name]) {
            diagnostics.push(
                diagnostic('undeclared_dependency', `Package "${name}" must be declared with an exact version`, file)
            )
        }
    }
    for (const [name, version] of Object.entries(project.dependencies)) {
        if (admittedDependencies.get(name) !== version) {
            diagnostics.push(
                diagnostic(
                    'dependency_unavailable',
                    `Package "${name}" at ${version} is not admitted to the canvas build image`
                )
            )
        }
    }
    const insights = new Set(project.capabilities.posthog.insights)
    const events = new Set(project.capabilities.posthog.captureEvents)
    const origins = new Set(project.capabilities.network.origins)
    if (origins.size > 0)
        diagnostics.push(
            diagnostic(
                'network_capability_unavailable',
                'External network access is unavailable until canvas capability approval is implemented'
            )
        )
    for (const [file, source] of Object.entries(project.files)) {
        for (const match of source.matchAll(/\bph\.loadInsight\s*\(\s*["']([^"']+)["']/g)) {
            if (!insights.has(match[1]))
                diagnostics.push(
                    diagnostic(
                        'undeclared_insight',
                        `Insight "${match[1]}" is not declared in canvas capabilities`,
                        file
                    )
                )
        }
        if (/\bph\.query\s*\(/.test(source) && !project.capabilities.posthog.inlineQueries) {
            diagnostics.push(
                diagnostic(
                    'undeclared_inline_query',
                    'Inline PostHog queries require the inlineQueries capability',
                    file
                )
            )
        }
        for (const match of source.matchAll(/\bph\.capture\s*\(\s*["']([^"']+)["']/g)) {
            if (!events.has(match[1]))
                diagnostics.push(
                    diagnostic(
                        'undeclared_capture_event',
                        `Capture event "${match[1]}" is not declared in canvas capabilities`,
                        file
                    )
                )
        }
        for (const match of source.matchAll(/\b(?:fetch|WebSocket|EventSource)\s*\(\s*["'](https:\/\/[^"']+)["']/g)) {
            const origin = new URL(match[1]).origin
            if (!origins.has(origin))
                diagnostics.push(
                    diagnostic(
                        'undeclared_network_origin',
                        `Network origin "${origin}" is not declared in canvas capabilities`,
                        file
                    )
                )
        }
    }
    return diagnostics.slice(0, 500)
}

function projectPlugin(project) {
    return {
        name: 'canvas-project',
        setup(pluginBuild) {
            pluginBuild.onResolve({ filter: /.*/ }, (args) => {
                if (args.kind === 'entry-point') return { path: normalizeProjectPath(args.path), namespace: 'canvas' }
                if (args.namespace === 'canvas' && (args.path.startsWith('.') || args.path.startsWith('/'))) {
                    const resolved = resolveProjectFile(project.files, args.importer, args.path)
                    return resolved
                        ? { path: resolved, namespace: 'canvas' }
                        : { errors: [{ text: `Canvas source file not found: ${args.path}` }] }
                }
                if (args.namespace === 'canvas') {
                    const name = packageName(args.path)
                    if (
                        nodeBuiltins.has(args.path) ||
                        nodeBuiltins.has(name) ||
                        args.path.includes('\\') ||
                        args.path.split('/').includes('..') ||
                        project.dependencies[name] !== admittedDependencies.get(name)
                    )
                        return { errors: [{ text: `Canvas dependency is not declared: ${args.path}` }] }
                    try {
                        return { path: require.resolve(args.path) }
                    } catch {
                        return { errors: [{ text: `Canvas dependency not found: ${args.path}` }] }
                    }
                }
                return null
            })
            pluginBuild.onLoad({ filter: /.*/, namespace: 'canvas' }, (args) => ({
                contents: project.files[args.path],
                loader: loaderFor(args.path),
                resolveDir: '/',
            }))
        },
    }
}

function contentSecurityPolicy(project) {
    const origins = project.capabilities.network.origins.join(' ')
    return [
        "default-src 'none'",
        "base-uri 'none'",
        "object-src 'none'",
        "form-action 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        `connect-src ${origins || "'none'"}`,
        `img-src 'self' data: blob:${origins ? ` ${origins}` : ''}`,
        "font-src 'self' data:",
        "media-src 'self' data: blob:",
        "worker-src 'self' blob:",
    ].join('; ')
}

function injectHead(html, markup) {
    if (/<head(?:\s[^>]*)?>/i.test(html)) return html.replace(/<head(?:\s[^>]*)?>/i, (head) => `${head}${markup}`)
    const doctype = html.match(/^\s*<!doctype[^>]*>/i)?.[0]
    return doctype ? html.replace(doctype, `${doctype}<head>${markup}</head>`) : `<head>${markup}</head>${html}`
}

function contentType(filePath) {
    if (filePath.endsWith('.html')) return 'text/html; charset=utf-8'
    if (filePath.endsWith('.css')) return 'text/css; charset=utf-8'
    if (filePath.endsWith('.js')) return 'text/javascript; charset=utf-8'
    if (filePath.endsWith('.json')) return 'application/json; charset=utf-8'
    return 'application/octet-stream'
}

async function buildCanvas(project) {
    const diagnostics = validateProject(project)
    const html = project.files[project.entryHtml]
    if (remoteScript.test(html))
        diagnostics.push(
            diagnostic(
                'remote_script',
                'Remote scripts must be installed as pinned dependencies and bundled',
                project.entryHtml
            )
        )
    if (inlineScript.test(html))
        diagnostics.push(
            diagnostic(
                'inline_script',
                'Inline scripts are not allowed; move code into the module entry',
                project.entryHtml
            )
        )
    if (inlineEventHandler.test(html))
        diagnostics.push(
            diagnostic(
                'inline_event_handler',
                'Inline HTML event handlers are blocked; register events from a local module',
                project.entryHtml
            )
        )
    if (javascriptUrl.test(html))
        diagnostics.push(
            diagnostic('javascript_url', 'JavaScript URLs are not allowed in canvas HTML', project.entryHtml)
        )
    if (diagnostics.length) return { ok: false, diagnostics: diagnostics.slice(0, 500) }
    const moduleMatches = [...html.matchAll(moduleScript)]
    if (moduleMatches.length > 1)
        return {
            ok: false,
            diagnostics: [
                diagnostic(
                    'multiple_entries',
                    'Canvas HTML may load at most one local module entry',
                    project.entryHtml
                ),
            ],
        }
    const artifactFiles = {}
    let builtHtml = html
    const moduleSource = moduleMatches[0]?.[1]
    if (moduleSource) {
        const entry = normalizeProjectPath(moduleSource)
        if (!(entry in project.files))
            return {
                ok: false,
                diagnostics: [diagnostic('missing_entry', `Canvas module entry "${entry}" does not exist`)],
            }
        try {
            const output = await build({
                absWorkingDir: process.cwd(),
                entryPoints: [entry],
                bundle: true,
                write: false,
                outdir: 'out',
                entryNames: 'assets/main',
                assetNames: 'assets/[name]-[hash]',
                chunkNames: 'assets/chunk-[hash]',
                format: 'esm',
                platform: 'browser',
                target: 'es2022',
                treeShaking: true,
                minify: true,
                legalComments: 'none',
                sourcemap: false,
                plugins: [projectPlugin(project)],
                loader: {
                    '.png': 'dataurl',
                    '.jpg': 'dataurl',
                    '.jpeg': 'dataurl',
                    '.gif': 'dataurl',
                    '.svg': 'dataurl',
                    '.woff': 'dataurl',
                    '.woff2': 'dataurl',
                },
            })
            for (const file of output.outputFiles) {
                const relative = normalizeProjectPath(path.relative(path.join(process.cwd(), 'out'), file.path))
                artifactFiles[relative] = file.text
            }
            builtHtml = builtHtml.replace(moduleScript, '<script type="module" src="./assets/main.js"></script>')
            if (artifactFiles['assets/main.css'])
                builtHtml = builtHtml.replace(/<\/head>/i, '<link rel="stylesheet" href="./assets/main.css" /></head>')
        } catch (error) {
            const errors = error?.errors ?? []
            return {
                ok: false,
                diagnostics: errors.length
                    ? errors.slice(0, 500).map((entry) =>
                          diagnostic(
                              'compile_error',
                              entry.text ?? 'Canvas compilation failed',
                              entry.location?.file ? normalizeProjectPath(entry.location.file) : undefined,
                              {
                                  ...(entry.location?.line ? { line: entry.location.line } : {}),
                                  ...(entry.location?.column !== undefined ? { column: entry.location.column } : {}),
                              }
                          )
                      )
                    : [diagnostic('build_failed', error instanceof Error ? error.message : String(error))],
            }
        }
    }
    artifactFiles['index.html'] = builtHtml
    artifactFiles[runtimePath] = runtime
    const escapedCsp = contentSecurityPolicy(project).replaceAll('&', '&amp;').replaceAll('"', '&quot;')
    artifactFiles['index.html'] = injectHead(
        artifactFiles['index.html'],
        `<meta http-equiv="Content-Security-Policy" content="${escapedCsp}" /><script src="./${runtimePath}"></script>`
    )
    const files = Object.entries(artifactFiles)
        .map(([filePath, content]) => ({
            path: filePath,
            contentType: contentType(filePath),
            bytes: Buffer.byteLength(content),
            sha256: createHash('sha256').update(content).digest('hex'),
        }))
        .sort((left, right) => left.path.localeCompare(right.path))
    return {
        ok: true,
        diagnostics: [],
        artifactFiles,
        manifest: {
            schemaVersion: 1,
            entryHtml: 'index.html',
            files,
            canvasSdkVersion: project.canvasSdkVersion,
            dependencies: project.dependencies,
            capabilities: project.capabilities,
        },
    }
}

let input = ''
for await (const chunk of process.stdin) input += chunk
try {
    const request = JSON.parse(input)
    process.stdout.write(JSON.stringify(await buildCanvas(request.project)))
} catch (error) {
    process.stdout.write(
        JSON.stringify({
            ok: false,
            diagnostics: [diagnostic('invalid_build_request', error instanceof Error ? error.message : String(error))],
        })
    )
}
