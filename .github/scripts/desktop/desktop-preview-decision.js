const PREVIEW_LABELS = ['hogbox-preview', 'desktop-preview', 'no-preview']
const BOT_LOGIN_PATTERN = /^(dependabot|renovate|github-actions|snyk-bot|posthog-bot|mendral-app|greptileai|coderabbitai|sentry-io)\b/i

function decidePreview({
    event,
    action,
    pr,
    repository,
    labels,
    label,
    autoPreviewEligible = false,
    desktopChanged = true,
}) {
    const skip = { build: false, desktop: false, installers: false, teardown: false, retireDesktop: false }
    if (pr.head?.repo?.full_name !== repository || pr.state === 'closed') {
        return skip
    }
    const manual = event === 'workflow_dispatch'
    const login = pr.user?.login || ''
    const isBot = pr.user?.type === 'Bot' || /\[bot\]$/i.test(login) || BOT_LOGIN_PATTERN.test(login)
    const labelEvent = action === 'labeled' || action === 'unlabeled'
    if (labelEvent && !PREVIEW_LABELS.includes(label)) {
        return skip
    }
    // Cleanup runs before the bot guard: a manually dispatched bot preview must
    // still tear down when no-preview lands or the last preview label leaves.
    if (labels.includes('no-preview')) {
        return action === 'labeled' && label === 'no-preview'
            ? { ...skip, teardown: true, retireDesktop: true }
            : skip
    }
    const desktop = labels.includes('desktop-preview')
    // A bot can only ever build via manual dispatch, so it has no automatic
    // eligibility: during a cleanup calculation its only demand is the labels.
    const backend = desktop || labels.includes('hogbox-preview') || (autoPreviewEligible && !isBot)
    if (action === 'unlabeled' && label !== 'no-preview') {
        return {
            ...skip,
            teardown: !backend,
            retireDesktop: label === 'desktop-preview',
        }
    }
    if (!manual && isBot) {
        return skip
    }
    if (action === 'ready_for_review' && (desktop || labels.includes('hogbox-preview'))) {
        return skip
    }
    const build = manual || backend
    return { ...skip, build, desktop: build && desktop, installers: build && desktop && desktopChanged }
}

module.exports = { decidePreview }
