import { appendFileSync, readFileSync } from 'node:fs'
import { posix } from 'node:path'
import { pathToFileURL } from 'node:url'
import { parseArgs } from 'node:util'

const BASELINE_PATH = 'frontend/snapshots.yml'

// Returns each snapshot id with its lines as written, so a failure can print them for restoring.
// The YAML writer emits a key over 128 characters in the explicit `? key` form.
export function readSnapshotEntries(yamlText) {
    const entries = new Map()
    let inSnapshots = false
    let current = null
    for (const line of yamlText.split('\n')) {
        if (/^\s*(#|$)/.test(line)) {
            continue
        }
        if (/^\S/.test(line)) {
            inSnapshots = /^snapshots:\s*(#.*)?$/.test(line)
            current = null
            continue
        }
        if (!inSnapshots) {
            continue
        }
        const key = /^ {4}(?:\? +(['"]?)([^\s'":?]+)\1|(['"]?)([^\s'":?]+)\3:)(?:\s+#.*)?\s*$/.exec(line)
        if (key) {
            current = [line]
            entries.set(key[2] ?? key[4], current)
        } else if (current) {
            current.push(line)
        }
    }
    return entries
}

// Storybook sanitizes a story id to exactly one `--` (title--export), and the test runner appends
// `--<viewport width>`, `--<theme>` and `--<browser>` to it, so the first two segments name the story.
export function storyIdOf(snapshotId) {
    return snapshotId.split('--').slice(0, 2).join('--')
}

export function readSnapshottedStories(indexJsonText, storybookRoot) {
    const entries = JSON.parse(indexJsonText).entries ?? {}
    const stories = new Map()
    for (const entry of Object.values(entries)) {
        if (entry?.type !== 'story' || (entry.tags ?? []).includes('test-skip')) {
            continue
        }
        stories.set(entry.id, entry.importPath ? posix.normalize(posix.join(storybookRoot, entry.importPath)) : null)
    }
    return stories
}

// A story the PR's Visual Review run renders shows a wrong removal there for review. Only stories
// that run skips can lose every entry silently.
export function findLiveRemovals({ baseIds, headIds, stories, renderedFiles }) {
    const storiesWithHeadEntries = new Set([...headIds].map(storyIdOf))
    const removals = []
    for (const id of baseIds) {
        if (headIds.has(id)) {
            continue
        }
        const storyId = storyIdOf(id)
        if (!stories.has(storyId) || storiesWithHeadEntries.has(storyId) || renderedFiles.has(stories.get(storyId))) {
            continue
        }
        removals.push(id)
    }
    return removals.sort()
}

export function formatFailure(removals, baseEntries) {
    const storyCount = new Set(removals.map(storyIdOf)).size
    const stories = storyCount === 1 ? 'story that still exists' : 'stories that still exist'
    return [
        `This PR removes every ${BASELINE_PATH} entry of ${storyCount} ${stories}.`,
        "This PR's Visual Review run does not render these stories, so it cannot show the removal.",
        'The merge queue renders every story and rejects the batch that holds this PR.',
        '',
        `To fix it, add these lines back to ${BASELINE_PATH} under snapshots, in alphabetical order:`,
        '',
        ...removals.flatMap((id) => baseEntries.get(id)),
        '',
        "If a story should no longer take snapshots, tag it 'test-skip' in its story file and this check passes.",
    ].join('\n')
}

function main() {
    const { values } = parseArgs({
        options: {
            'base-snapshots': { type: 'string' },
            'head-snapshots': { type: 'string' },
            'storybook-index': { type: 'string' },
            'storybook-root': { type: 'string', default: 'common/storybook' },
            'rendered-files': { type: 'string' },
        },
    })
    for (const required of ['base-snapshots', 'head-snapshots', 'storybook-index', 'rendered-files']) {
        if (!values[required]) {
            console.error(`Missing --${required}`)
            process.exit(2)
        }
    }

    const baseEntries = readSnapshotEntries(readFileSync(values['base-snapshots'], 'utf8'))
    const removals = findLiveRemovals({
        baseIds: new Set(baseEntries.keys()),
        headIds: new Set(readSnapshotEntries(readFileSync(values['head-snapshots'], 'utf8')).keys()),
        stories: readSnapshottedStories(readFileSync(values['storybook-index'], 'utf8'), values['storybook-root']),
        renderedFiles: new Set(JSON.parse(readFileSync(values['rendered-files'], 'utf8'))),
    })
    if (removals.length === 0) {
        console.log(`No ${BASELINE_PATH} entry was removed for a story that still takes snapshots.`)
        return
    }

    const message = formatFailure(removals, baseEntries)
    console.log(message)
    if (process.env.GITHUB_STEP_SUMMARY) {
        appendFileSync(
            process.env.GITHUB_STEP_SUMMARY,
            `### Snapshot baselines removed\n\n\`\`\`\n${message}\n\`\`\`\n`
        )
    }
    if (process.env.GITHUB_ACTIONS) {
        const annotation = message.replaceAll('%', '%25').replaceAll('\r', '%0D').replaceAll('\n', '%0A')
        console.log(`::error title=Snapshot baselines removed for existing stories::${annotation}`)
    }
    process.exit(1)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main()
}
