import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import posthog from 'posthog-js'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { postHogTeamCohortBannerLogic } from './postHogTeamCohortBannerLogic'

describe('postHogTeamCohortBannerLogic', () => {
    let logic: ReturnType<typeof postHogTeamCohortBannerLogic.build>

    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: true })
        superpowersLogic.mount()
        logic = postHogTeamCohortBannerLogic()
        logic.mount()
        superpowersLogic.actions.setExcludedFromPostHogTeamCohort(true)
    })

    afterEach(() => {
        logic.unmount()
    })

    it('shows the banner again after a remount, and after leaving the cohort again', () => {
        logic.actions.dismissBanner()
        expect(logic.values.bannerVisible).toBe(false)

        logic.unmount()
        logic = postHogTeamCohortBannerLogic()
        logic.mount()
        expect(logic.values.bannerVisible).toBe(true)

        logic.actions.dismissBanner()
        superpowersLogic.actions.setExcludedFromPostHogTeamCohort(true)
        expect(logic.values.bannerVisible).toBe(true)
    })

    it('rejoining clears the opt-out and hides the banner', () => {
        logic.actions.rejoinPostHogTeamCohort(false)

        expect(superpowersLogic.values.excludedFromPostHogTeamCohort).toBe(false)
        expect(logic.values.bannerVisible).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith('nav posthog team cohort banner rejoin clicked', {
            nav_collapsed: false,
        })
    })
})
