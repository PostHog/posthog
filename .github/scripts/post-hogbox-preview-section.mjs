#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { postSection, updateSectionIfPresent } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const LEGACY_PREFIXES = ['<!-- hogbox-preview-comment -->']

export function buildHogboxPreviewSection({
    state,
    sha = '',
    runUrl,
    url,
    boxId,
    penId,
    consoleHost,
    frontendSwapped,
    readySeconds,
}) {
    const commit = sha.slice(0, 7)

    if (state === 'building') {
        return {
            status: 'info',
            summary: 'building',
            body: [
                "Spinning up PostHog for this PR on a hogland hogbox. This section updates in place when it's ready (usually a few minutes).",
                '',
                `<sub>commit \`${commit}\` &middot; <a href="${runUrl}">build log</a></sub>`,
            ].join('\n'),
        }
    }

    if (state === 'failed') {
        return {
            status: 'fail',
            summary: 'build failed',
            body: [
                `The preview didn't come up for commit \`${commit}\`. See the **[build log](${runUrl})** for the failing step. It'll retry on the next push.`,
                '',
                '<sub>Previews are optional and never block merging. A failure here is often a hogland or tailnet hiccup rather than anything in your PR, so the check stays green and this section is the status.</sub>',
            ].join('\n'),
        }
    }

    if (state === 'torn-down') {
        return {
            status: 'info',
            summary: 'torn down',
            body: 'The preview for this PR was torn down (label removed or `no-preview` added). Re-add the `hogbox-preview` label to bring it back.',
        }
    }

    if (state !== 'ready') {
        throw new Error(`Unknown hogbox preview section state: ${state}`)
    }

    // A backend-only preview serves the :master SPA, so only claim the PR's frontend when it was swapped in.
    const running = frontendSwapped
        ? "this PR's backend **and** frontend, on the PostHog `:master` base"
        : "this PR's backend on the PostHog `:master` base (frontend unchanged by this PR)"
    // The CLI parser can surface a missing pen id as the literal string 'None'.
    const adminUrl =
        consoleHost && penId && penId !== 'None' ? `https://${consoleHost}/console/fleet/pens/${penId}` : null
    const readyIn = readySeconds ? ` &middot; ready in ${readySeconds}s (push → usable)` : ''

    return {
        status: 'ok',
        summary: `ready, <a href="${url}">open the preview</a>`,
        body: [
            `### [▶ Open the preview](${url})`,
            '',
            '| | |',
            '|--|--|',
            '| 🔑 **Login** | `test@posthog.com` / `12345678` (demo data) |',
            `| 🧩 **Running** | ${running} |`,
            '| 🔗 **Link** | **stable across rebuilds**: a re-push swaps the box underneath, the URL stays |',
            '| 🔒 **Access** | tailnet only (PostHog VPN) |',
            ...(adminUrl ? [`| 🛠️ **Admin** | [inspect & debug state in hogland](${adminUrl}) |`] : []),
            '| 💤 **Idle** | sleeps after ~30 min idle (snapshot to S3, zero node cost) and wakes on your next visit in ~30s, behind a brief "waking up" screen |',
            '',
            `<sub>commit \`${commit}\` &middot; box \`${boxId}\`${readyIn} &middot; <a href="${runUrl}">build log</a> &middot; rebuilds on every push, torn down on close</sub>`,
        ].join('\n'),
    }
}

async function main() {
    const [state] = process.argv.slice(2)
    const section = buildHogboxPreviewSection({
        state,
        sha: process.env.SHA,
        runUrl: `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`,
        url: process.env.URL,
        boxId: process.env.BOX,
        penId: process.env.PEN,
        consoleHost: process.env.CONSOLE_HOST,
        frontendSwapped: process.env.SWAP === 'true',
        readySeconds: process.env.READY_SECONDS,
    })
    const post = state === 'torn-down' ? updateSectionIfPresent : postSection
    await post({ id: 'hogbox-preview', ...section }, { legacyPrefixes: LEGACY_PREFIXES })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
