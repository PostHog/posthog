import { dayjs } from 'lib/dayjs'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { isOnSimpleOnboardingArm } from '../simple/simpleOnboardingArm'

export const WELCOME_NAV_ITEM_MAX_PROJECT_AGE_DAYS = 7

/** Whether the sidebar links to the welcome page: only on the simple onboarding arm, and only for a new project. */
export function isWelcomeNavItemShown(
    projectCreatedAt: string | undefined,
    featureFlags: FeatureFlagsSet,
    now: dayjs.Dayjs = dayjs()
): boolean {
    if (!projectCreatedAt || now.diff(dayjs(projectCreatedAt), 'day', true) >= WELCOME_NAV_ITEM_MAX_PROJECT_AGE_DAYS) {
        return false
    }
    // Read the flag only after the age check, because the sidebar renders for every user.
    return isOnSimpleOnboardingArm(featureFlags)
}
