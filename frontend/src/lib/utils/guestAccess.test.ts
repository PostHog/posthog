import { OrganizationMembershipLevel } from 'lib/constants'
import { Scene } from 'scenes/sceneTypes'

import { AppContext } from '~/types'

import { isGuestUser, isSceneDeniedToGuest } from './guestAccess'

describe('guestAccess', () => {
    const setMembershipLevel = (membership_level: OrganizationMembershipLevel): void => {
        window.POSTHOG_APP_CONTEXT = {
            current_user: { organization: { membership_level } },
        } as unknown as AppContext
    }

    afterEach(() => {
        window.POSTHOG_APP_CONTEXT = undefined as unknown as AppContext
    })

    it.each([
        ['a guest opening a dashboard', OrganizationMembershipLevel.Guest, Scene.Dashboard, false],
        ['a guest opening a notebook', OrganizationMembershipLevel.Guest, Scene.Notebook, false],
        ['a guest opening persons', OrganizationMembershipLevel.Guest, Scene.Persons, true],
        ['a guest opening the recording page', OrganizationMembershipLevel.Guest, Scene.ReplaySingle, true],
        ['a member opening persons', OrganizationMembershipLevel.Member, Scene.Persons, false],
    ])('for %s', (_name, level, scene, denied) => {
        setMembershipLevel(level)
        expect(isGuestUser()).toBe(level === OrganizationMembershipLevel.Guest)
        expect(isSceneDeniedToGuest(scene, true)).toBe(denied)
        expect(isSceneDeniedToGuest(Scene.ErrorAccessDenied, undefined)).toBe(false)
    })
})
