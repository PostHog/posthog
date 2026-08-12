#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

export function buildDocsPreviewSection({ triggerStatus, deploymentUrl, deploymentId, runUrl, now = new Date() }) {
    if (triggerStatus !== 'success') {
        return {
            status: 'fail',
            summary: 'preview build failed to start',
            body: `The docs preview build could not be triggered. [View the workflow logs](${runUrl}) for details.`,
        }
    }

    const previewUrl = deploymentUrl || 'https://posthog.com'
    const inspectorUrl = deploymentId
        ? `https://vercel.com/post-hog/posthog/${deploymentId}`
        : 'https://vercel.com/post-hog/posthog'
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
        status: 'info',
        summary: 'preview build triggered',
        body: [
            'Docs from this PR will be published at posthog.com.',
            '',
            '| Project | Preview | Updated (UTC) |',
            '| :--- | :--- | :--- |',
            `| [posthog.com](${inspectorUrl}) | [Open preview](${previewUrl}) | ${timestamp} |`,
            '',
            'The preview should be ready in about 10 minutes. Open the preview at `/handbook/engineering/`.',
        ].join('\n'),
    }
}

async function main() {
    const repositoryUrl = `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}`
    const section = buildDocsPreviewSection({
        triggerStatus: process.env.TRIGGER_STATUS,
        deploymentUrl: process.env.DEPLOYMENT_URL,
        deploymentId: process.env.DEPLOYMENT_ID,
        runUrl: `${repositoryUrl}/actions/runs/${process.env.GITHUB_RUN_ID}`,
    })
    await postSection({ id: 'docs-preview', ...section }, { legacyPrefixes: ['[docs-preview]:'] })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
