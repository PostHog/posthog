#!/usr/bin/env node
import fs from 'node:fs'
import { pathToFileURL } from 'node:url'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

function readFile(path, fallback = '') {
    try {
        return fs.readFileSync(path, 'utf8')
    } catch {
        return fallback
    }
}

function dropletDetails(dropletInfo) {
    return {
        instanceUrl: dropletInfo.match(/URL: (.*)/)?.[1] ?? '',
        sshCommand: dropletInfo.match(/SSH: (.*)/)?.[1] ?? '',
        dropletIp: dropletInfo.match(/Droplet IP: (.*)/)?.[1] ?? '',
    }
}

export function buildHobbySection({ state, previewMode, sha, runNumber, runUrl, buildConclusion, files = {} }) {
    const commit = sha.slice(0, 7)
    const metadata = `**Commit:** \`${commit}\`  \n**Workflow run:** [#${runNumber}](${runUrl})`
    const mode = previewMode ? 'Preview (persistent)' : 'Smoke test (ephemeral)'

    if (state === 'initial') {
        return {
            status: 'info',
            summary: 'setting up preview instance',
            body: `Setting up a persistent preview instance. This takes about 30 minutes.\n\n${metadata}`,
        }
    }
    if (state === 'build-failed') {
        return {
            status: 'fail',
            summary: 'Docker image build failed',
            body: [
                `The Docker image build did not complete successfully (status: ${buildConclusion || 'unknown'}).`,
                '',
                `[View the workflow logs](${runUrl}), fix the build error, and push a new commit to retry.`,
                '',
                metadata,
            ].join('\n'),
        }
    }
    if (state === 'image-ready') {
        return {
            status: 'info',
            summary: 'Docker image ready, creating instance',
            body: `The Docker image is ready. The preview instance is being created.\n\n${metadata}`,
        }
    }

    const dropletInfo = files.dropletInfo ?? ''
    const { instanceUrl, sshCommand, dropletIp } = dropletDetails(dropletInfo)
    if (state === 'instance-created') {
        return {
            status: 'info',
            summary: instanceUrl ? `running smoke tests at ${instanceUrl}` : 'instance created, running smoke tests',
            body: [
                'The preview instance is ready and smoke tests are running.',
                instanceUrl ? `\n**URL:** ${instanceUrl}` : '',
                '',
                metadata,
            ].join('\n'),
        }
    }

    if (state !== 'final') {
        throw new Error(`Unknown hobby section state: ${state}`)
    }

    const testPassed = files.testExitCode === '0'
    const instanceCreated = dropletInfo.length > 0
    let status = 'ok'
    let summary = previewMode ? 'preview deployment ready' : 'smoke test passed'
    let errorSection = ''
    if (!instanceCreated) {
        status = 'fail'
        summary = 'instance creation failed'
        errorSection = `### Deployment error

The instance could not be created. [View the workflow logs](${runUrl}) for the failing step.`
    } else if (!testPassed) {
        status = 'fail'
        summary = 'smoke tests failed'
        const recentLogs = (files.cloudInitLogs || 'Could not fetch cloud-init logs')
            .trim()
            .split('\n')
            .slice(-30)
            .join('\n')
        errorSection = `### Test failure

The deployment was created but health checks failed.

${instanceUrl ? `- Try accessing manually: ${instanceUrl}\n` : ''}${sshCommand ? `- SSH to debug: \`${sshCommand}\`` : ''}

<details>
<summary>Recent cloud-init logs</summary>

\`\`\`
${recentLogs}
\`\`\`
</details>`
    }

    const access = [
        instanceUrl ? `**URL:** ${instanceUrl}` : '',
        sshCommand ? `**SSH:** \`${sshCommand}\`` : '',
        dropletIp ? `**IP:** \`${dropletIp}\`` : '',
    ].filter(Boolean)
    const details =
        dropletInfo && testPassed
            ? `<details>\n<summary>Full instance details</summary>\n\n\`\`\`\n${dropletInfo.trim()}\n\`\`\`\n</details>`
            : ''
    const output = files.output || 'Could not read hobby-ci output'
    const sections = []
    if (access.length > 0) {
        sections.push(access.join('\n'))
    }
    sections.push(`**Mode:** ${mode}\n${metadata}`)
    if (errorSection) {
        sections.push(errorSection)
    }
    if (details) {
        sections.push(details)
    }
    sections.push(`<details>\n<summary>Deployment output</summary>\n\n\`\`\`\n${output.trim()}\n\`\`\`\n</details>`)
    return {
        status,
        summary,
        body: sections.join('\n\n'),
    }
}

async function main() {
    const [state] = process.argv.slice(2)
    const repositoryUrl = `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}`
    const section = buildHobbySection({
        state,
        previewMode: process.env.PREVIEW_MODE === 'true',
        sha: process.env.GITHUB_SHA || '',
        runNumber: process.env.GITHUB_RUN_NUMBER || '',
        runUrl: `${repositoryUrl}/actions/runs/${process.env.GITHUB_RUN_ID}`,
        buildConclusion: process.env.BUILD_CONCLUSION,
        files: {
            dropletInfo: readFile('/tmp/droplet_info.txt'),
            cloudInitLogs: readFile('/tmp/cloud-init-output.log'),
            output: readFile('/tmp/hobby-ci-output.txt', 'Could not read hobby-ci output'),
            testExitCode: process.env.TEST_EXIT_CODE,
        },
    })
    await postSection({ id: 'hobby-deploy', ...section }, { legacyPrefixes: ['<!-- hobby-ci-comment -->'] })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
