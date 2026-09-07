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
    if (!manual && (pr.user?.type === 'Bot' || /\[bot\]$/i.test(login) || BOT_LOGIN_PATTERN.test(login))) {
        return skip
    }
    const labelEvent = action === 'labeled' || action === 'unlabeled'
    if (labelEvent && !PREVIEW_LABELS.includes(label)) {
        return skip
    }
    if (labels.includes('no-preview')) {
        return action === 'labeled' && label === 'no-preview'
            ? { ...skip, teardown: true, retireDesktop: true }
            : skip
    }
    const desktop = labels.includes('desktop-preview')
    const backend = desktop || labels.includes('hogbox-preview') || autoPreviewEligible
    if (action === 'unlabeled' && label !== 'no-preview') {
        return {
            ...skip,
            teardown: !backend,
            retireDesktop: label === 'desktop-preview',
        }
    }
    if (action === 'ready_for_review' && (desktop || labels.includes('hogbox-preview'))) {
        return skip
    }
    const build = manual || backend
    return { ...skip, build, desktop: build && desktop, installers: build && desktop && desktopChanged }
}

module.exports = { decidePreview }
