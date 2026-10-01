import { appendFileSync, readFileSync } from 'node:fs'
import { posix } from 'node:path'
import { pathToFileURL } from 'node:url'
import { parseArgs } from 'node:util'

const BASELINE_PATH = 'frontend/snapshots.yml'

export function readSnapshotIds(yamlText) {
    const ids = new Set()
    let inSnapshots = false
    for (const line of yamlText.split('\n')) {
        if (/^\S/.test(line)) {
            inSnapshots = /^snapshots:\s*$/.test(line)
            continue
        }
        const match = inSnapshots && /^ {4}(['"]?)([^\s'":]+)\1:\s*$/.exec(line)
        if (match) {
            ids.add(match[2])
        }
    }
    return ids
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

// A PR that edits a story file renders that story in its own Visual Review run, so a wrong removal
// shows up there for review. Only stories the PR run does not render can lose every entry silently.
export function findLiveRemovals({ baseIds, headIds, stories, changedFiles }) {
    const storiesWithHeadEntries = new Set([...headIds].map(storyIdOf))
    const removals = []
    for (const id of baseIds) {
        if (headIds.has(id)) {
            continue
        }
        const storyId = storyIdOf(id)
        if (!stories.has(storyId) || storiesWithHeadEntries.has(storyId) || changedFiles.has(stories.get(storyId))) {
            continue
        }
        removals.push(id)
    }
    return removals.sort()
}

export function formatFailure(removals) {
    const storyCount = new Set(removals.map(storyIdOf)).size
    return [
        `This PR removes every ${BASELINE_PATH} entry of ${storyCount} ${storyCount === 1 ? 'story' : 'stories'} that still ${storyCount === 1 ? 'exists' : 'exist'}.`,
        'This PR does not change those story files, so its own Visual Review run does not render them.',
        'The merge queue renders every story, reports these snapshots as new, and fails.',
        '',
        'Removed entries:',
        ...removals.map((id) => `  ${id}`),
        '',
        'To fix it, restore these entries. Either copy them back from the master version of the file, or run:',
        `  git checkout origin/master -- ${BASELINE_PATH}`,
        "then commit and push. Visual Review then asks you to approve this PR's snapshot changes again and commits them.",
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
            'changed-files': { type: 'string' },
        },
    })
    for (const required of ['base-snapshots', 'head-snapshots', 'storybook-index', 'changed-files']) {
        if (!values[required]) {
            console.error(`Missing --${required}`)
            process.exit(2)
        }
    }

    const removals = findLiveRemovals({
        baseIds: readSnapshotIds(readFileSync(values['base-snapshots'], 'utf8')),
        headIds: readSnapshotIds(readFileSync(values['head-snapshots'], 'utf8')),
        stories: readSnapshottedStories(readFileSync(values['storybook-index'], 'utf8'), values['storybook-root']),
        changedFiles: new Set(readFileSync(values['changed-files'], 'utf8').split('\n').filter(Boolean)),
    })
    if (removals.length === 0) {
        console.log(`No ${BASELINE_PATH} entry was removed for a story that still takes snapshots.`)
        return
    }

    const message = formatFailure(removals)
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

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
    main()
}
