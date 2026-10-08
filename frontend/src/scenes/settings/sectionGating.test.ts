import { SettingSection, SettingSectionId } from '~/scenes/settings/types'

import { findUnavailableSection } from './sectionGating'

const section = (id: SettingSectionId, overrides: Partial<SettingSection> = {}): SettingSection => ({
    id,
    title: 'Access resolution preview',
    level: 'organization',
    settings: [],
    ...overrides,
})

describe('findUnavailableSection', () => {
    const gatedSection = section('organization-access-resolution', {
        flag: 'ACCESS_CONTROL_RESOLUTION_PREVIEW',
        unavailableFallback: { sectionId: 'organization-roles', label: 'Go to access control settings' },
    })

    it('explains a section the feature flag hides', () => {
        expect(
            findUnavailableSection({
                sectionId: 'organization-access-resolution',
                visibleSections: [],
                allSections: [gatedSection],
                gatesResolved: true,
                doesMatchFlags: () => false,
                isAdminOrOwner: true,
            })
        ).toEqual({
            id: 'organization-access-resolution',
            title: 'Access resolution preview',
            reason: 'not-enabled',
            fallback: { sectionId: 'organization-roles', label: 'Go to access control settings' },
        })
    })

    it('explains a section only admins can open', () => {
        expect(
            findUnavailableSection({
                sectionId: 'organization-access-resolution',
                visibleSections: [],
                allSections: [gatedSection],
                gatesResolved: true,
                doesMatchFlags: () => true,
                isAdminOrOwner: false,
            })
        ).toMatchObject({ reason: 'admin-only' })
    })

    it('waits for the flags and the membership level before it calls a section admin-only', () => {
        expect(
            findUnavailableSection({
                sectionId: 'organization-access-resolution',
                visibleSections: [],
                allSections: [gatedSection],
                gatesResolved: false,
                doesMatchFlags: () => true,
                isAdminOrOwner: false,
            })
        ).toBeNull()
    })

    it.each([
        ['the section is visible', 'organization-access-resolution' as SettingSectionId, [gatedSection]],
        ['the section does not exist', 'organization-security' as SettingSectionId, []],
        ['no section is requested', null, []],
    ])('returns nothing when %s', (_name, sectionId, visibleSections) => {
        expect(
            findUnavailableSection({
                sectionId,
                visibleSections,
                allSections: [gatedSection],
                gatesResolved: true,
                doesMatchFlags: () => true,
                isAdminOrOwner: false,
            })
        ).toBeNull()
    })

    it('matches an environment section against its project id', () => {
        expect(
            findUnavailableSection({
                sectionId: 'project-replay',
                visibleSections: [],
                allSections: [section('environment-replay', { flag: 'ACCESS_CONTROL_RESOLUTION_PREVIEW' })],
                gatesResolved: true,
                doesMatchFlags: () => false,
                isAdminOrOwner: true,
            })
        ).toMatchObject({ id: 'environment-replay', reason: 'not-enabled' })
    })
})
