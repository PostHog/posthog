#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

// Maximum page links to list before the section falls back to a count.
const MAX_PAGE_LINKS = 25

// The site URL is a pure function of the file path (see docs/README.md):
// strip the docs/published/ prefix and drop the .md/.mdx extension.
function toSitePath(filePath) {
    return '/' + filePath.replace(/^docs\/published\//, '').replace(/\.mdx?$/, '')
}

function docPageLinks(changedPaths, previewUrl) {
    const pages = changedPaths.filter((path) => path.startsWith('docs/published/') && /\.mdx?$/.test(path))
    const shown = pages.slice(0, MAX_PAGE_LINKS).map((path) => {
        const sitePath = toSitePath(path)
        return `| [\`${sitePath}\`](${previewUrl}${sitePath}) |`
    })
    return { shown, hidden: pages.length - shown.length }
}

export function buildDocsPreviewSection({
    triggerStatus,
    deploymentUrl,
    deploymentId,
    runUrl,
    changedPaths = [],
    now = new Date(),
}) {
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

    const { shown, hidden } = docPageLinks(changedPaths, previewUrl)
    const body = ['Docs from this PR will be published at posthog.com.', '']

    if (shown.length > 0) {
        body.push('| Page |', '| :--- |', ...shown)
        if (hidden > 0) {
            body.push('', `…and ${hidden} more changed page${hidden === 1 ? '' : 's'}.`)
        }
    } else {
        body.push(`[Open preview](${previewUrl})`)
    }

    body.push(
        '',
        `The preview should be ready in about 10 minutes. [Inspect the build on Vercel](${inspectorUrl}). Updated ${timestamp} UTC.`
    )

    return {
        status: 'info',
        summary: 'preview build triggered',
        body: body.join('\n'),
    }
}

async function main() {
    const repositoryUrl = `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}`
    const changedPaths = (process.env.CHANGED_DOCS || '')
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
    const section = buildDocsPreviewSection({
        triggerStatus: process.env.TRIGGER_STATUS,
        deploymentUrl: process.env.DEPLOYMENT_URL,
        deploymentId: process.env.DEPLOYMENT_ID,
        runUrl: `${repositoryUrl}/actions/runs/${process.env.GITHUB_RUN_ID}`,
        changedPaths,
    })
    await postSection({ id: 'docs-preview', ...section }, { legacyPrefixes: ['[docs-preview]:'] })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
