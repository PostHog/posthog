#!/usr/bin/env node

// Validates links in docs/ markdown files:
// 1. Relative links (./foo, ../bar) must resolve to existing files
//    - published/ docs: links must stay within docs/published/ (they get served on posthog.com)
//    - internal/ docs: links can point anywhere in the repo (GitHub-only)
// 2. Absolute posthog.com links that point to local docs should be relative instead
// 3. Absolute posthog.com links must return HTTP 200/301/302

const fs = require('fs')
const path = require('path')

const DOCS_ROOT = path.resolve(__dirname, '../../docs')
const PUBLISHED_ROOT = path.join(DOCS_ROOT, 'published')
const LINK_RE = /\[.*?\]\(([^)]+)\)/g
const POSTHOG_URL_RE = /https:\/\/posthog\.com\/[^\s)"]+/g
const MAX_CONCURRENT = 10
const RETRIES = 3
const TIMEOUT_MS = 10_000
const RETRY_DELAY_MS = 2_000

function findMarkdownFiles(dir) {
    const results = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            results.push(...findMarkdownFiles(full))
        } else if (/\.mdx?$/.test(entry.name)) {
            results.push(full)
        }
    }
    return results
}

function extractLinks(content) {
    const links = []
    let match
    while ((match = LINK_RE.exec(content)) !== null) {
        links.push(match[1])
    }
    return links
}

function resolveRelativeLink(fromFile, link) {
    const target = link.split('#')[0]
    if (!target) return null
    if (/^https?:\/\/|^mailto:|^\//.test(target)) return null

    const dir = path.dirname(fromFile)
    const resolved = path.resolve(dir, target)
    const isPublished = fromFile.startsWith(PUBLISHED_ROOT + path.sep)

    // Published docs must not link outside docs/published/
    if (isPublished && !resolved.startsWith(PUBLISHED_ROOT)) {
        return {
            file: path.relative(DOCS_ROOT, fromFile),
            link,
            resolved: path.relative(DOCS_ROOT, resolved),
            reason: 'escapes docs/published/ boundary',
        }
    }

    // Check: exact file, .md, .mdx, index.md, index.mdx
    const candidates = [
        resolved,
        resolved + '.md',
        resolved + '.mdx',
        path.join(resolved, 'index.md'),
        path.join(resolved, 'index.mdx'),
    ]

    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) return null // found, no error
    }

    return { file: path.relative(DOCS_ROOT, fromFile), link, resolved: path.relative(DOCS_ROOT, resolved) }
}

// Build a set of URL paths that map to local published docs.
// e.g. "handbook/engineering/project-structure" if published/handbook/engineering/project-structure.md exists
function buildPublishedUrlIndex() {
    const index = new Set()
    if (!fs.existsSync(PUBLISHED_ROOT)) return index

    for (const file of findMarkdownFiles(PUBLISHED_ROOT)) {
        let rel = path.relative(PUBLISHED_ROOT, file)
        // Strip .md/.mdx extension
        rel = rel.replace(/\.(mdx?)$/, '')
        // Strip /index suffix (index files map to the directory path)
        rel = rel.replace(/\/index$/, '')
        index.add(rel)
    }
    return index
}

function findAbsoluteLinksToLocalDocs(files, publishedIndex) {
    const issues = []
    for (const file of files) {
        const content = fs.readFileSync(file, 'utf8')
        let match
        const re = new RegExp(POSTHOG_URL_RE.source, 'g')
        while ((match = re.exec(content)) !== null) {
            const url = match[0].replace(/[,.)]+$/, '')
            const urlPath = url.replace('https://posthog.com/', '').split('#')[0].replace(/\/$/, '')
            if (publishedIndex.has(urlPath)) {
                issues.push({ file: path.relative(DOCS_ROOT, file), url })
            }
        }
    }
    return issues
}

function collectPosthogUrls(files) {
    const urls = new Set()
    for (const file of files) {
        const content = fs.readFileSync(file, 'utf8')
        let match
        while ((match = POSTHOG_URL_RE.exec(content)) !== null) {
            // Strip trailing punctuation that regex might capture
            let url = match[0].replace(/[,.)]+$/, '')
            urls.add(url)
        }
    }
    return [...urls].sort()
}

async function fetchWithRetry(url) {
    for (let attempt = 1; attempt <= RETRIES; attempt++) {
        try {
            const controller = new AbortController()
            const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

            const res = await fetch(url, {
                method: 'HEAD',
                redirect: 'manual',
                signal: controller.signal,
            })
            clearTimeout(timer)

            const status = res.status
            if (status === 200 || status === 301 || status === 302 || status === 308) {
                return { url, ok: true, status }
            }

            if (attempt < RETRIES) {
                await new Promise((r) => setTimeout(r, RETRY_DELAY_MS))
            } else {
                return { url, ok: false, status }
            }
        } catch (err) {
            if (attempt < RETRIES) {
                await new Promise((r) => setTimeout(r, RETRY_DELAY_MS))
            } else {
                return { url, ok: false, status: err.name === 'AbortError' ? 'timeout' : err.code || 'error' }
            }
        }
    }
}

async function checkPosthogUrls(urls) {
    const failures = []
    // Process in batches to avoid hammering the server
    for (let i = 0; i < urls.length; i += MAX_CONCURRENT) {
        const batch = urls.slice(i, i + MAX_CONCURRENT)
        const results = await Promise.all(batch.map(fetchWithRetry))
        for (const r of results) {
            if (!r.ok) failures.push(r)
        }
    }
    return failures
}

async function main() {
    if (!fs.existsSync(DOCS_ROOT)) {
        console.log('No docs/ directory found, skipping.')
        process.exit(0)
    }

    const files = findMarkdownFiles(DOCS_ROOT)
    console.log(`Found ${files.length} markdown files in docs/\n`)

    let exitCode = 0

    // 1. Check relative links
    console.log('--- Checking relative links ---')
    const brokenRelative = []
    for (const file of files) {
        const content = fs.readFileSync(file, 'utf8')
        const links = extractLinks(content)
        for (const link of links) {
            const err = resolveRelativeLink(file, link)
            if (err) brokenRelative.push(err)
        }
    }

    if (brokenRelative.length > 0) {
        for (const { file, link, resolved, reason } of brokenRelative) {
            const detail = reason || `resolved to ${resolved}`
            console.log(`  ❌ ${file}: ${link} (${detail})`)
        }
        console.log(`\n${brokenRelative.length} broken relative link(s) found.\n`)
        exitCode = 1
    } else {
        console.log(`  ✅ All relative links resolve to existing files\n`)
    }

    // 2. Check for absolute links to local docs (should be relative)
    console.log('--- Checking for absolute links to local docs ---')
    const publishedIndex = buildPublishedUrlIndex()
    const shouldBeRelative = findAbsoluteLinksToLocalDocs(files, publishedIndex)

    if (shouldBeRelative.length > 0) {
        for (const { file, url } of shouldBeRelative) {
            console.log(`  ❌ ${file}: ${url} (exists locally, use a relative link instead)`)
        }
        console.log(`\n${shouldBeRelative.length} link(s) should be relative.\n`)
        exitCode = 1
    } else {
        console.log(`  ✅ No absolute links to local docs found\n`)
    }

    // 3. Check posthog.com links
    console.log('--- Checking posthog.com links ---')
    const urls = collectPosthogUrls(files)

    if (urls.length === 0) {
        console.log('  No posthog.com links found, skipping.\n')
    } else {
        console.log(`  Found ${urls.length} unique posthog.com URLs to check`)
        const brokenUrls = await checkPosthogUrls(urls)

        if (brokenUrls.length > 0) {
            for (const { url, status } of brokenUrls) {
                console.log(`  ❌ ${url} (${status})`)
            }
            console.log(`\n${brokenUrls.length} broken posthog.com link(s) found.`)
            console.log('These may be stale references to moved or deleted pages.\n')
            exitCode = 1
        } else {
            console.log(`  ✅ All ${urls.length} posthog.com links are reachable\n`)
        }
    }

    process.exit(exitCode)
}

main()
