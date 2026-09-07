#!/usr/bin/env node

// Pure decision table for the `desktop-preview` label: given a PR event's
// facts, decide whether to provision/upgrade a desktop preview (backend
// profile + preview installers), tear one down, or do nothing.
//
// Centralized and table-driven so the workflow's `decide` job stays a thin
// adapter and every row of the semantics has a unit test. Two kinds of demand
// share one backend: `hogbox-preview` (backend + web frontend) and
// `desktop-preview` (backend + desktop installers). Backend demand is the OR
// of the two; desktop demand is `desktop-preview` alone, so removing
// `hogbox-preview` while `desktop-preview` stays must NOT tear down the box.
//
// Run with: node --test .github/scripts/desktop/desktop-preview-decision.test.js

const HOGBOX_LABEL = 'hogbox-preview'
const DESKTOP_LABEL = 'desktop-preview'
const NO_PREVIEW_LABEL = 'no-preview'

const BOT_LOGIN_PATTERN =
    /^(dependabot|renovate|github-actions|snyk-bot|posthog-bot|mendral-app|greptileai|coderabbitai|sentry-io)\b/i

function isBotAuthor(pr) {
    const login = (pr && pr.user && pr.user.login) || ''
    return (
        (pr && pr.user && pr.user.type) === 'Bot' || /\[bot\]$/i.test(login) || BOT_LOGIN_PATTERN.test(login)
    )
}

function isSameRepo(pr, repository) {
    return Boolean(pr && pr.head && pr.head.repo && pr.head.repo.full_name === repository)
}

/**
 * Decide the desktop-preview action for one PR event.
 *
 * @param {object} input
 * @param {string} input.event - workflow event name.
 * @param {string} [input.action] - pull_request action (labeled, unlabeled, …).
 * @param {object} input.pr - the pull_request payload (or a dispatched PR fetched via API).
 * @param {string} input.repository - `owner/repo` of the base repository.
 * @param {string[]} input.labels - current PR label names.
 * @param {string} [input.label] - the label this labeled/unlabeled event carried.
 * @returns {{action: 'build'|'teardown'|'none', desktop: boolean, backend: boolean, reason: string}}
 */
function decideDesktopPreview(input) {
    const { event, action, pr, repository, labels, label } = input
    const desktop = labels.includes(DESKTOP_LABEL)
    const backendDemand =
        desktop ||
        labels.includes(HOGBOX_LABEL) ||
        // Frontend auto-preview eligibility keeps a shared backend alive too.
        (labels.length >= 0 && backendWantedByAutoPreview(input))
    const optedOut = labels.includes(NO_PREVIEW_LABEL)

    const result = (action_, desktop_, backend_, reason) => ({
        action: action_,
        desktop: desktop_,
        backend: backend_,
        reason,
    })

    if (event === 'workflow_dispatch') {
        // An explicit act by someone with Actions write: reconcile current
        // head. The caller's fork guard is the security gate.
        return result('build', desktop, true, 'workflow_dispatch → reconcile')
    }

    if (!isSameRepo(pr, repository)) {
        return result('none', false, false, 'fork PR → no preview, no credentials')
    }
    if (isBotAuthor(pr)) {
        return result('none', false, false, 'bot author → no preview')
    }

    // Teardown fast paths (idempotent — a no-op when nothing is up).
    if (action === 'unlabeled' && label === DESKTOP_LABEL) {
        // The backend survives when hogbox-preview or auto-preview still
        // wants it; only the desktop packaging path retires.
        return result(
            'teardown',
            false,
            backendWantedByOtherDemand(input),
            `desktop-preview removed → retire desktop artifacts; backend kept only if other demand remains`,
        )
    }
    if (action === 'labeled' && label === NO_PREVIEW_LABEL) {
        // The explicit opt-out wins over every demand.
        return result('teardown', false, false, 'no-preview added → tear down')
    }

    if (action === 'labeled' || action === 'unlabeled') {
        // Only label transitions that change demand are expensive; anything
        // else is a no-op so unrelated label churn never rebuilds.
        const buildRelevant =
            (action === 'labeled' && label === DESKTOP_LABEL) ||
            (action === 'unlabeled' && label === NO_PREVIEW_LABEL)
        if (!buildRelevant) {
            return result('none', desktop, backendDemand, `label ${action} '${label}' — not desktop-preview-relevant`)
        }
    }

    if (optedOut) {
        return result('none', false, false, 'no-preview present → suppressed')
    }

    if (desktop) {
        return result('build', true, true, 'desktop-preview label → backend profile + installers')
    }

    // No desktop demand: an ordinary hogbox build may still be wanted, but
    // that is the existing workflow's decision, not this module's.
    return result('none', false, backendDemand, 'no desktop-preview demand')
}

function backendWantedByAutoPreview(input) {
    // The existing decide job computes auto-preview eligibility (frontend
    // diff); this module only needs to know it when the caller passes it.
    return Boolean(input.autoPreviewEligible)
}

function backendWantedByOtherDemand(input) {
    const labels = input.labels.filter((l) => l !== DESKTOP_LABEL)
    return (
        labels.includes(HOGBOX_LABEL) ||
        backendWantedByAutoPreview({ ...input, labels })
    )
}

module.exports = {
    decideDesktopPreview,
    isBotAuthor,
    isSameRepo,
    DESKTOP_LABEL,
    HOGBOX_LABEL,
    NO_PREVIEW_LABEL,
}
