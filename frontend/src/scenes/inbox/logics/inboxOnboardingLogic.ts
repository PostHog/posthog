import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { signalSourcesLogic } from '../signalSourcesLogic'
import type { inboxOnboardingLogicType } from './inboxOnboardingLogicType'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './reportListLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

/** How the self-driving onboarding presents itself over the inbox. */
export type InboxOnboardingMode = 'loading' | 'takeover' | 'banner' | 'none'

export interface OnboardingModeInputs {
    /** Both source + scout config loaders have settled, so the set-up verdict is trustworthy. */
    isSetupLoaded: boolean
    /** At least one signal source or scout is watching. */
    isSelfDrivingSetUp: boolean
    /** Both tab count loaders have settled (returned, or failed) – the work verdict is trustworthy. */
    areCountsResolved: boolean
    /** There are existing reports or PRs in the inbox. */
    hasExistingWork: boolean
    /** The banner was dismissed this session. */
    bannerDismissed: boolean
}

/**
 * Pure decision for how (if at all) the onboarding shows.
 *
 * The `'loading'` state matters for UX: until we know whether self-driving is set up, the scene
 * shows a neutral loader rather than the inbox skeleton – otherwise a not-set-up user sees the
 * skeleton for a moment and then gets yanked to the takeover (a jarring jolt). Set-up users skip
 * the loader as soon as the config check resolves, without waiting on the report counts.
 */
export function computeOnboardingMode({
    isSetupLoaded,
    isSelfDrivingSetUp,
    areCountsResolved,
    hasExistingWork,
    bannerDismissed,
}: OnboardingModeInputs): InboxOnboardingMode {
    if (!isSetupLoaded) {
        return 'loading'
    }
    // Set-up users go straight to their inbox – no need to wait on the report counts.
    if (isSelfDrivingSetUp) {
        return 'none'
    }
    // Not set up: the report counts decide takeover (empty inbox) vs. banner (work already exists).
    if (!areCountsResolved) {
        return 'loading'
    }
    if (hasExistingWork) {
        return bannerDismissed ? 'none' : 'banner'
    }
    return 'takeover'
}

/**
 * Decides how the single-command self-driving onboarding presents itself. There are no in-app
 * setup steps – the user runs one wizard command in their repo – so "set up" is read straight
 * from what the wizard turns on: at least one signal source or scout watching.
 *
 * When self-driving is NOT set up, the presentation depends on whether there's anything to show:
 * - nothing landed yet (no reports or PRs) → a full-pane takeover. Nothing to block, so we lean in.
 * - reports or PRs already exist (they had sources/scouts before) → a sleek, non-blocking banner
 *   above the inbox, so the team keeps access to their work while we entice them to re-enable.
 *
 * The banner is session-dismissable; it returns next time the inbox is opened still un-set-up.
 * The takeover has no dismiss – there's nothing behind it to reach.
 */
export const inboxOnboardingLogic = kea<inboxOnboardingLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxOnboardingLogic']),

    connect(() => ({
        values: [
            signalSourcesLogic,
            ['sourceConfigs', 'enabledSourcesCount'],
            scoutFleetLogic,
            ['scoutConfigs', 'enabledCount as enabledScoutsCount'],
            // Mount the pulls + reports count loaders directly (cheap limit=1 each) so we know
            // whether there's existing work even during a takeover, when the tab bar that usually
            // mounts these isn't rendered. Same keyed instances the tab bar uses – no double-fetch.
            reportListLogic({ tabKey: 'pulls', listParams: INBOX_FLAT_TAB_LIST_PARAMS.pulls }),
            ['count as pullsCount', 'countLoading as pullsCountLoading'],
            reportListLogic({ tabKey: 'reports', listParams: INBOX_FLAT_TAB_LIST_PARAMS.reports }),
            ['count as reportsCount', 'countLoading as reportsCountLoading'],
        ],
    })),

    actions({
        dismissBanner: true,
    }),

    reducers({
        bannerDismissed: [
            false,
            {
                dismissBanner: () => true,
            },
        ],
    }),

    selectors({
        isSelfDrivingSetUp: [
            (s) => [s.enabledSourcesCount, s.enabledScoutsCount],
            (enabledSourcesCount, enabledScoutsCount): boolean => enabledSourcesCount + enabledScoutsCount > 0,
        ],
        // Both source + scout config loaders have settled, so the set-up verdict is trustworthy.
        isSetupLoaded: [
            (s) => [s.sourceConfigs, s.scoutConfigs],
            (sourceConfigs, scoutConfigs): boolean => sourceConfigs !== null && scoutConfigs !== null,
        ],
        // Counts are "resolved" once both limit=1 requests have returned, OR once neither is still
        // loading (so a failed count request can't strand the onboarding on the loading state – this
        // is only consulted after the configs have loaded, by which point the counts have started).
        areCountsResolved: [
            (s) => [s.pullsCount, s.reportsCount, s.pullsCountLoading, s.reportsCountLoading],
            (pullsCount, reportsCount, pullsCountLoading, reportsCountLoading): boolean =>
                (pullsCount !== null && reportsCount !== null) || (!pullsCountLoading && !reportsCountLoading),
        ],
        hasExistingWork: [
            (s) => [s.pullsCount, s.reportsCount],
            (pullsCount, reportsCount): boolean => (pullsCount ?? 0) + (reportsCount ?? 0) > 0,
        ],
        onboardingMode: [
            (s) => [s.isSetupLoaded, s.isSelfDrivingSetUp, s.areCountsResolved, s.hasExistingWork, s.bannerDismissed],
            (
                isSetupLoaded,
                isSelfDrivingSetUp,
                areCountsResolved,
                hasExistingWork,
                bannerDismissed
            ): InboxOnboardingMode =>
                computeOnboardingMode({
                    isSetupLoaded,
                    isSelfDrivingSetUp,
                    areCountsResolved,
                    hasExistingWork,
                    bannerDismissed,
                }),
        ],
    }),
])
