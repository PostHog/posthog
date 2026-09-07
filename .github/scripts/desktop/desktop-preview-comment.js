const MARKER = '<!-- desktop-preview-comment -->'

// Built from a string rather than written as a regex literal: a literal that
// opens with `<!--` trips Semgrep's JavaScript parser and fails the scan.
function recordPattern(name) {
    return new RegExp(`<!-- desktop-preview-${name} (\\{.*?\\}) -->`)
}

function readRecord(body, name) {
    const match = body ? body.match(recordPattern(name)) : null
    if (!match) {
        return null
    }
    try {
        return JSON.parse(match[1])
    } catch {
        return null
    }
}

/**
 * Build the sticky desktop-preview comment.
 *
 * The comment holds two independent records, each in its own marker: the
 * backend the box runs, and the installers testers download. They move at
 * different speeds, so a run updates only the record it has news about, and
 * carries the other one over untouched.
 *
 * That split is what survives the interleaving: a backend-only push takes the
 * head SHA away from the installer run that is still building, so when that
 * run finally reports, its own backend numbers are stale but its installers
 * are the only ones that exist. Run id orders the installer records, so a
 * late report can never overwrite a newer build.
 */
function composeDesktopPreviewComment({
    prNumber,
    sha,
    headSha,
    url,
    backendReady,
    gateway,
    installersRequested,
    results,
    runId,
    runUrl,
    existingBody = null,
}) {
    const headMoved = headSha !== sha
    const current = [results.macos, results.windows, results.linux]
    // Only real build results replace the stored record: a skipped job (failed
    // bring-up) must not destroy the download links testers already have.
    const built = installersRequested && current.some((result) => result !== 'skipped')
    if (headMoved && !built) {
        return { skip: true, reason: `head moved to ${headSha} and this run built no installers` }
    }

    const priorInstallers = readRecord(existingBody, 'installers')
    const priorBackend = readRecord(existingBody, 'backend')
    const candidate = built
        ? { runUrl, runId: Number(runId), sha, macos: results.macos, windows: results.windows, linux: results.linux }
        : null
    const newerThanStored = candidate && Number(priorInstallers?.runId ?? 0) <= candidate.runId
    let installers = null
    if (candidate && newerThanStored) {
        installers = candidate
    } else if (priorInstallers && priorInstallers.macos !== 'skipped') {
        installers = priorInstallers
    }

    const fresh = { sha, url, ready: backendReady, gateway }
    const backend = headMoved && priorBackend ? priorBackend : fresh

    const rows = installers
        ? [
              ['macOS (arm64 + x64)', installers.macos],
              ['Windows x64', installers.windows],
              ['Linux (x64 + arm64)', installers.linux],
          ]
        : []
    const platform = (row) => (row[1] === 'success' ? '✅ built' : row[1] === 'skipped' ? '— skipped' : `❌ ${row[1]}`)
    const allOk = rows.length > 0 && rows.every((row) => row[1] === 'success')
    const anyOk = rows.some((row) => row[1] === 'success')
    const status = !backend.ready
        ? '❌ backend failed'
        : !installers
          ? '⏳ backend ready, no installers yet'
          : allOk
            ? '✅ ready'
            : anyOk
              ? '⚠️ partially built'
              : '❌ installer build failed'
    const installerSection = installers
        ? `**[Download installers from run ${installers.runUrl.split('/').pop()}](${installers.runUrl}#artifacts)** (built from ${installers.sha.slice(0, 7)}; requires repo access, expires in 7 days).\n\n` +
          `| Platform | Status |\n|--|--|\n` +
          rows.map((row) => `| ${row[0]} | ${platform(row)} |`).join('\n') +
          `\n\n`
        : `No installers have been built for this preview yet. Push a change under \`products/desktop/\` or re-add the \`desktop-preview\` label to build them.\n\n`
    const agents = backend.gateway
        ? `Agents run through this preview's own LLM gateway on Bedrock. Claude models only.`
        : `Agent model calls are unavailable in this preview: its gateway did not start.`

    const body =
        `${MARKER}\n` +
        (installers ? `<!-- desktop-preview-installers ${JSON.stringify(installers)} -->\n` : '') +
        `<!-- desktop-preview-backend ${JSON.stringify(backend)} -->\n` +
        `### 🖥️ Desktop preview &middot; ${status}\n\n` +
        (backend.url ? `Backend: ${backend.url} (VPN required), running ${backend.sha.slice(0, 7)}.\n\n` : '') +
        `Sign in with \`desktop-tester-1@example.com\` or \`desktop-tester-2@example.com\`, password \`posthog-desktop-preview\`.\n\n` +
        `${agents}\n\n` +
        installerSection +
        `The macOS builds are **signed but not notarized**. Clear the quarantine flag once:\n\n` +
        '```sh\n' +
        `xattr -dr com.apple.quarantine "/Applications/PostHog Preview PR ${prNumber}.app"` +
        '\n```\n\n' +
        `Pushes that touch only backend code update the backend in place; installers rebuild when desktop code changes. ` +
        `Backend test data and sessions can reset on a push.\n\n` +
        `<sub>Preview installers have automatic updates and product analytics disabled.</sub>`

    return { body }
}

module.exports = { composeDesktopPreviewComment, readRecord, MARKER }
