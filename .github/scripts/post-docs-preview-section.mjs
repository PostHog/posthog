#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

export function buildDocsPreviewSection({
    triggerStatus,
    deploymentState,
    deploymentUrl,
    deploymentId,
    runUrl,
    now = new Date(),
}) {
    const inspectorUrl = deploymentId
        ? `https://vercel.com/post-hog/posthog/${deploymentId}`
        : 'https://vercel.com/post-hog/posthog'

    if (triggerStatus !== 'success') {
        return {
            status: 'fail',
            summary: 'preview build failed to start',
            body: `The docs preview build could not be triggered. [View the workflow logs](${runUrl}) for details.`,
        }
    }

    // Vercel cancels a build when a newer docs preview supersedes it, so report the real
    // outcome instead of an "Open preview" link that lands on a cancelled page.
    if (deploymentState === 'CANCELED') {
        return {
            status: 'fail',
            summary: 'preview build cancelled',
            body: [
                'Vercel cancelled this build because a newer docs preview started for another PR.',
                '',
                `Push again to start a fresh build, or [open the Vercel inspector](${inspectorUrl}) to retry.`,
            ].join('\n'),
        }
    }

    if (deploymentState === 'ERROR') {
        return {
            status: 'fail',
            summary: 'preview build errored',
            body: [
                'The docs preview build ended with an error.',
                '',
                `[Open the Vercel inspector](${inspectorUrl}) for the build logs.`,
            ].join('\n'),
        }
    }

    // The build is still running past the poll window: do not claim success yet.
    if (deploymentState && deploymentState !== 'READY') {
        return {
            status: 'info',
            summary: 'preview build still running',
            body: [
                `The docs preview build is still in progress (state: ${deploymentState}).`,
                '',
                `Track it in the [Vercel inspector](${inspectorUrl}).`,
            ].join('\n'),
        }
    }

    const previewUrl = deploymentUrl || 'https://posthog.com'
    const timestamp = now.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZone: 'UTC',
    })

    return {
        status: 'ok',
        summary: 'preview build ready',
        body: [
            'Docs from this PR are published at posthog.com.',
            '',
            '| Project | Preview | Updated (UTC) |',
            '| :--- | :--- | :--- |',
            `| [posthog.com](${inspectorUrl}) | [Open preview](${previewUrl}) | ${timestamp} |`,
            '',
            'Open the preview at `/handbook/engineering/`.',
        ].join('\n'),
    }
}

async function main() {
    const repositoryUrl = `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}`
    const section = buildDocsPreviewSection({
        triggerStatus: process.env.TRIGGER_STATUS,
        deploymentState: process.env.DEPLOYMENT_STATE,
        deploymentUrl: process.env.DEPLOYMENT_URL,
        deploymentId: process.env.DEPLOYMENT_ID,
        runUrl: `${repositoryUrl}/actions/runs/${process.env.GITHUB_RUN_ID}`,
    })
    await postSection({ id: 'docs-preview', ...section }, { legacyPrefixes: ['[docs-preview]:'] })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
