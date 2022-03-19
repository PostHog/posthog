import {
    LicensePlan,
    LicenseType,
    OrganizationInviteType,
    OrganizationMemberType,
    OrganizationType,
    PersonProperty,
    TeamType,
} from '~/types'
import { OrganizationMembershipLevel } from './constants'

export const MOCK_TEAM_ID: TeamType['id'] = 997
export const MOCK_ORGANIZATION_ID: OrganizationType['id'] = 'ABCD'

export const MOCK_DEFAULT_TEAM: Partial<TeamType> = {
    id: MOCK_TEAM_ID,
    ingested_event: true,
    completed_snippet_onboarding: true,
    effective_membership_level: OrganizationMembershipLevel.Admin,
}

export const MOCK_DEFAULT_ORGANIZATION: Partial<OrganizationType> = {
    id: MOCK_ORGANIZATION_ID,
    membership_level: OrganizationMembershipLevel.Admin,
}

export const MOCK_DEFAULT_BASIC_USER = {
    id: 178,
    uuid: '99952779-ee06-43d5-b441-8af718b10d65',
    distinct_id: 'mock-user-178-distinct-id',
    first_name: 'John',
    email: 'john.doe@posthog.com',
}

export const MOCK_DEFAULT_ORGANIZATION_MEMBER: OrganizationMemberType = {
    id: '71fc7b7a-6267-47ae-ab62-f7f62aaed5da',
    user: MOCK_DEFAULT_BASIC_USER,
    level: OrganizationMembershipLevel.Owner,
    joined_at: '2020-09-24T15:05:26.758796Z',
    updated_at: '2020-09-24T15:05:26.758837Z',
}

export const MOCK_DEFAULT_ORGANIZATION_INVITE: OrganizationInviteType = {
    id: '83666ba4-4740-4ca3-94d9-d2b6b9b8afa6',
    target_email: 'test@posthog.com',
    first_name: '',
    emailing_attempt_made: true,
    is_expired: true,
    created_by: MOCK_DEFAULT_BASIC_USER,
    created_at: '2022-03-11T16:44:01.264613Z',
    updated_at: '2022-03-11T16:44:01.318717Z',
}

export const MOCK_DEFAULT_LICENSE: LicenseType = {
    id: 1,
    key: 'license-key',
    plan: LicensePlan.Scale,
    valid_until: '2025-03-11T14:05:45.338000Z',
    max_users: 21312,
    created_at: '2022-03-11T14:05:36.107000Z',
}

export const MOCK_PERSON_PROPERTIES: PersonProperty[] = [
    { id: 1, name: 'location', count: 1 },
    { id: 2, name: 'role', count: 2 },
    { id: 3, name: 'height', count: 3 },
    { id: 4, name: '$browser', count: 4 },
]
