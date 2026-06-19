#!/usr/bin/env node

// Resolve PostHog code ownership from products/*/product.yaml + CODEOWNERS.
//
// Resolution order (mirrors the establishing-code-ownership skill):
//   1. A file under products/<name>/ is owned by that product.yaml's `owners:`
//      (beats any CODEOWNERS entry). Products without a product.yaml fall through.
//   2. Otherwise the CODEOWNERS files decide. Within each file the last matching
//      glob wins. Across the two files a blocking CODEOWNERS owner wins when
//      present, else the CODEOWNERS-soft owner applies. A blocking glob with no
//      owner (a reset, used so product teams can edit infra-owned trees) clears
//      only the blocking owner; it does not erase a soft mapping.
//   3. No owner from either file means unowned.
//
// Glob matching is NOT reimplemented here: it reuses fileMatchesPattern from
// .github/scripts/assign-reviewers.js, the same matcher PostHog's reviewer
// auto-assigner runs in CI, so answers stay in lockstep with what CI assigns.
// That matcher is intentionally stricter than GitHub's docs: patterns are
// anchored, a slash-free pattern matches only at the root, and a directory must
// carry a trailing slash (or /**) to match its contents.
//
// Usage:
//   ownership.js file <path>... [--all]        who owns these files
//   ownership.js team <slug-or-handle> [prefix...] every tracked file a team owns
//   ownership.js unowned [prefix...]              every tracked file with no owner
//
// Data goes to stdout; counts and notes go to stderr (so you can pipe stdout).

const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

function findRepoRoot(start) {
    let dir = start
    for (;;) {
        if (fs.existsSync(path.join(dir, '.github', 'CODEOWNERS'))) {
            return dir
        }
        const parent = path.dirname(dir)
        if (parent === dir) {
            throw new Error('could not locate repo root (no .github/CODEOWNERS found above this script)')
        }
        dir = parent
    }
}

const REPO_ROOT = findRepoRoot(__dirname)
const { fileMatchesPattern } = require(path.join(REPO_ROOT, '.github', 'scripts', 'assign-reviewers.js'))
if (typeof fileMatchesPattern !== 'function') {
    throw new Error('.github/scripts/assign-reviewers.js no longer exports fileMatchesPattern; ownership resolver is out of sync with CI')
}

// Bare product.yaml slug -> @PostHog/<slug>; an explicit @handle is left as-is.
function toHandle(owner) {
    return owner.startsWith('@') ? owner : `@PostHog/${owner}`
}

// @PostHog/team-x or @team-x or team-x -> team-x (for comparison).
function toSlug(owner) {
    if (owner.startsWith('@PostHog/')) return owner.slice('@PostHog/'.length)
    if (owner.startsWith('@')) return owner.slice(1)
    return owner
}

// Literal prefix before the first glob wildcard. The matcher anchors `^`, so a
// file can only match a rule if it starts with this; checking it first skips the
// regex build for non-candidates and keeps a full-repo sweep fast.
function literalPrefix(pattern) {
    const i = pattern.search(/[*?]/)
    if (i === -1) return pattern
    // The matcher leaves `?` as a regex quantifier (it makes the preceding char
    // optional), so the guaranteed literal prefix ends one char earlier there.
    return pattern[i] === '?' ? pattern.slice(0, Math.max(0, i - 1)) : pattern.slice(0, i)
}

function parseCodeowners(file, label) {
    if (!fs.existsSync(file)) return []
    const rules = []
    fs.readFileSync(file, 'utf8')
        .split('\n')
        .forEach((raw, idx) => {
            const line = raw.trim()
            if (!line || line.startsWith('#')) return
            const tokens = line.split(/\s+/)
            rules.push({
                pattern: tokens[0],
                owners: tokens.slice(1),
                source: label,
                lineno: idx + 1,
                prefix: literalPrefix(tokens[0]),
            })
        })
    return rules
}

// Pull the `owners:` value out of a product.yaml without a YAML dependency.
// Handles all three forms: block list, inline list, and a bare scalar.
function parseProductOwners(content) {
    const owners = []
    let inOwners = false
    for (const raw of content.split('\n')) {
        const line = raw.replace(/\s+#.*$/, '').trimEnd()
        if (!line.trim() || /^\s*#/.test(raw)) continue
        const ownersMatch = line.match(/^owners\s*:\s*(.*)$/)
        if (ownersMatch) {
            const rest = ownersMatch[1].trim()
            if (rest.startsWith('[')) {
                const close = rest.lastIndexOf(']')
                const inner = rest.slice(1, close === -1 ? rest.length : close)
                for (const item of inner.split(',')) {
                    const value = item.trim().replace(/^["']|["']$/g, '')
                    if (value) owners.push(value)
                }
            } else if (rest) {
                owners.push(rest.replace(/^["']|["']$/g, ''))
            } else {
                inOwners = true // block list follows on the next lines
            }
            continue
        }
        if (!inOwners) continue
        const m = line.match(/^\s+-\s+(.+?)$/)
        if (m) {
            owners.push(m[1].replace(/^["']|["']$/g, '').trim())
            continue
        }
        if (/^\S/.test(raw)) inOwners = false
    }
    return owners
}

function loadProductOwners(root) {
    const map = new Map()
    const productsDir = path.join(root, 'products')
    if (!fs.existsSync(productsDir)) return map
    for (const entry of fs.readdirSync(productsDir, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue
        const yaml = path.join(productsDir, entry.name, 'product.yaml')
        if (!fs.existsSync(yaml)) continue
        const owners = parseProductOwners(fs.readFileSync(yaml, 'utf8'))
            .filter((slug) => slug && slug !== 'team-CHANGEME') // a bootstrap placeholder, not a real team
            .map(toHandle)
        if (owners.length) map.set(entry.name, owners)
    }
    return map
}

function src(rule) {
    return `${rule.source}:${rule.lineno} (${rule.pattern})`
}

class Resolver {
    constructor(root) {
        this.root = root
        this.productOwners = loadProductOwners(root)
        this.softRules = parseCodeowners(path.join(root, '.github', 'CODEOWNERS-soft'), 'CODEOWNERS-soft')
        this.hardRules = parseCodeowners(path.join(root, '.github', 'CODEOWNERS'), 'CODEOWNERS')
        this.rules = this.softRules.concat(this.hardRules)
    }

    lastMatch(rules, file) {
        for (let i = rules.length - 1; i >= 0; i--) {
            const rule = rules[i]
            if (!file.startsWith(rule.prefix)) continue
            if (fileMatchesPattern(file, rule.pattern)) return rule
        }
        return null
    }

    resolve(file) {
        if (file.startsWith('products/')) {
            const name = file.split('/')[1]
            if (name && this.productOwners.has(name)) {
                return { owners: this.productOwners.get(name), source: `products/${name}/product.yaml`, reset: false }
            }
        }
        const hard = this.lastMatch(this.hardRules, file)
        if (hard && hard.owners.length) return { owners: hard.owners, source: src(hard), reset: false }
        const soft = this.lastMatch(this.softRules, file)
        if (soft && soft.owners.length) return { owners: soft.owners, source: src(soft), reset: false }
        const reset = hard || soft
        if (reset) return { owners: [], source: src(reset), reset: true }
        return { owners: [], source: null, reset: false }
    }

    allMatches(file) {
        return this.rules.filter((rule) => file.startsWith(rule.prefix) && fileMatchesPattern(file, rule.pattern))
    }
}

function listTrackedFiles(root, prefixes) {
    const args = ['ls-files', '-z']
    if (prefixes.length) args.push('--', ...prefixes)
    const out = execFileSync('git', args, { cwd: root, maxBuffer: 1024 * 1024 * 512 }).toString('utf8')
    return out.split('\0').filter(Boolean)
}

// Turn a user-supplied path into a normalized repo-relative one. Prefers the
// repo-relative reading (the documented contract) so the answer doesn't depend
// on cwd; only falls back to cwd-relative when that is clearly what was meant.
// A return value starting with "../" means the input points outside the repo.
function normalizeInputPath(root, raw) {
    const repoRel = path.posix.normalize(raw.split(path.sep).join('/').replace(/^\/+/, ''))
    if (!path.isAbsolute(raw)) {
        const underRoot = fs.existsSync(path.join(root, repoRel))
        const underCwd = fs.existsSync(path.join(process.cwd(), raw))
        if (underRoot || !underCwd) return repoRel
    }
    const abs = path.isAbsolute(raw) ? raw : path.resolve(process.cwd(), raw)
    return path.relative(root, abs).split(path.sep).join('/')
}

function cmdFile(resolver, paths, showAll) {
    for (const raw of paths) {
        const rel = normalizeInputPath(resolver.root, raw)
        if (rel.startsWith('../') || path.isAbsolute(rel)) {
            console.error(`warning: ${raw} is outside the repo root; ownership only covers tracked repo files`)
        }
        const res = resolver.resolve(rel)
        console.log(rel)
        if (res.owners.length) {
            console.log(`  owners: ${res.owners.join(', ')}`)
            console.log(`  source: ${res.source}`)
        } else if (res.reset) {
            console.log('  owners: none (ownership explicitly cleared)')
            console.log(`  source: ${res.source}`)
        } else {
            console.log('  owners: none (no product.yaml or CODEOWNERS match)')
        }
        if (showAll) {
            const matches = resolver.allMatches(rel)
            if (matches.length) {
                console.log('  all CODEOWNERS matches (last wins):')
                for (const rule of matches) {
                    const owners = rule.owners.length ? rule.owners.join(', ') : '(reset)'
                    console.log(`    ${rule.source}:${rule.lineno}  ${rule.pattern}  -> ${owners}`)
                }
            }
        }
    }
}

function cmdTeam(resolver, team, prefixes) {
    const target = toSlug(team).toLowerCase()
    const files = listTrackedFiles(resolver.root, prefixes)
    const owned = files.filter((f) => resolver.resolve(f).owners.some((o) => toSlug(o).toLowerCase() === target))
    for (const f of owned) console.log(f)
    console.error(`${owned.length} file(s) owned by ${team}`)
}

function cmdUnowned(resolver, prefixes) {
    const files = listTrackedFiles(resolver.root, prefixes)
    const unowned = files.filter((f) => resolver.resolve(f).owners.length === 0)
    for (const f of unowned) console.log(f)
    console.error(`${unowned.length} unowned of ${files.length} tracked file(s)`)
}

function usage(message) {
    if (message) console.error(`error: ${message}`)
    console.error('usage:')
    console.error('  ownership.js file <path>... [--all]               who owns these files')
    console.error('  ownership.js team <slug-or-handle> [prefix...]    every tracked file a team owns')
    console.error('  ownership.js unowned [prefix...]                  every tracked file with no owner')
    process.exit(message ? 2 : 0)
}

function main(argv) {
    const [command, ...rest] = argv
    if (!command || command === '-h' || command === '--help') usage()
    const resolver = new Resolver(REPO_ROOT)
    if (command === 'file') {
        const paths = rest.filter((a) => a !== '--all')
        if (!paths.length) usage('file needs at least one path')
        cmdFile(resolver, paths, rest.includes('--all'))
    } else if (command === 'team') {
        if (!rest.length) usage('team needs a slug or handle')
        cmdTeam(resolver, rest[0], rest.slice(1))
    } else if (command === 'unowned') {
        cmdUnowned(resolver, rest)
    } else {
        usage(`unknown command: ${command}`)
    }
}

try {
    main(process.argv.slice(2))
} catch (err) {
    console.error(`error: ${err.message}`)
    process.exit(1)
}
