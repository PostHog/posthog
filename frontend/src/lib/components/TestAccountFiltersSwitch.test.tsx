import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/settings/sidePanelSettingsLogic'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { TestAccountFilterSwitch } from './TestAccountFiltersSwitch'

// Regression coverage for https://github.com/PostHog/posthog/pull/59112
// — clicking the gear icon next to "Filter out internal and test users" used to
// open the PostHog AI (Max) side panel instead of Settings on any scene whose
// `SIDE_PANEL_CONTEXT_KEY` selector did not declare a `settings_section`
// (experiments, SQL editor, LLM analytics, hog functions, etc.).
describe('TestAccountFilterSwitch — gear icon opens Settings, not the AI side panel', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        // Mount the side-panel state machinery directly. We deliberately do NOT
        // mount any scene logic, so `sceneSidePanelContext.settings_section` is
        // undefined — the exact condition under which the bug used to bite.
        sidePanelStateLogic.mount()
        sidePanelSettingsLogic.mount()
        sidePanelLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('routes the user to the Settings side panel when the gear icon is clicked', async () => {
        const onChange = jest.fn()
        render(<TestAccountFilterSwitch checked={false} onChange={onChange} />)

        // The LemonSwitch itself has role="switch"; the gear is the only plain button.
        const gear = screen.getByRole('button')
        await userEvent.click(gear)

        const stateValues = sidePanelStateLogic.values
        const enabledTabs = sidePanelLogic.values.enabledTabs

        expect(stateValues.sidePanelOpen).toBe(true)
        expect(stateValues.selectedTab).toBe(SidePanelTab.Settings)

        // The bug was that on a scene without `settings_section`, Settings was
        // missing from `enabledTabs`, so `SidePanel.tsx`'s fallback `useEffect`
        // flipped `selectedTab` to `Max`. Asserting Settings is enabled proves
        // the fallback's `!sidePanelOpenAndAvailable` precondition is false.
        expect(enabledTabs).toContain(SidePanelTab.Settings)
        expect(enabledTabs.includes(SidePanelTab.Max)).toBe(true)
        // Replicates the `sidePanelOpenAndAvailable` check from SidePanel.tsx —
        // when true, the fallback to Max cannot run.
        expect(enabledTabs.includes(stateValues.selectedTab!)).toBe(true)
    })

    it('forwards the explicit section and setting ids that scroll to internal-user-filtering', async () => {
        const onChange = jest.fn()
        render(<TestAccountFilterSwitch checked={false} onChange={onChange} />)

        await userEvent.click(screen.getByRole('button'))

        // `settings` carries the explicit args from `openSettingsPanel(...)`. The
        // Settings panel reads these to scroll the right setting into view.
        expect(sidePanelSettingsLogic.values.settings).toEqual({
            sectionId: 'project-product-analytics',
            settingId: 'internal-user-filtering',
        })
        expect(onChange).not.toHaveBeenCalled()
    })

    it('keeps the Settings nav-bar gear hidden on scenes without a settings_section after the click', async () => {
        const onChange = jest.fn()
        render(<TestAccountFilterSwitch checked={false} onChange={onChange} />)

        await userEvent.click(screen.getByRole('button'))

        // Settings is now in enabledTabs (so the panel can render and the fallback
        // doesn't flip to Max), but it is intentionally still hidden from the nav
        // bar — that gear icon should only appear when the scene declares a
        // `settings_section`.
        expect(sidePanelLogic.values.enabledTabs).toContain(SidePanelTab.Settings)
        expect(sidePanelLogic.values.visibleTabs).not.toContain(SidePanelTab.Settings)
    })

    it('does NOT enable Settings when openSidePanel(Settings) is called without explicit args', async () => {
        // This is the path the SidePanel storybook (`SidePanelSettings` story) uses:
        // `useActions(sidePanelStateLogic).openSidePanel(SidePanelTab.Settings)`. On
        // a scene without `settings_section` (e.g. the dashboards URL the stories
        // pin themselves to) Settings should remain unavailable so the fallback
        // useEffect in SidePanel.tsx still routes to Max — preserving the existing
        // storybook snapshot.
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Settings)

        expect(sidePanelLogic.values.enabledTabs).not.toContain(SidePanelTab.Settings)
        expect(sidePanelSettingsLogic.values.isExplicitSettings).toBe(false)
    })
})
