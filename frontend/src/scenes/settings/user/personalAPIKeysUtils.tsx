import { LemonDialog, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { OrganizationBasicType, PersonalAPIKeyType, TeamBasicType } from '~/types'

import { EditingKeyFormValues, KeyExpirationOption, expiresAtForOption, isExpired } from './personalAPIKeysLogic'

export const EXPIRY_DATE_FORMAT = 'MMMM D, YYYY'
export const EXPIRY_TIME_FORMAT = 'h:mm A'

export const EXPIRATION_PRESETS: LemonSelectOption<KeyExpirationOption>[] = [
    { value: 'never', label: 'Never' },
    { value: '1', label: '1 day' },
    { value: '7', label: '7 days' },
    { value: '30', label: '30 days' },
    { value: '90', label: '90 days' },
    { value: '365', label: '1 year' },
]

export const LEGACY_HASHING_TOOLTIP = 'This key uses legacy hashing. Roll or delete it to upgrade.'

export const DELETE_KEY_DESCRIPTION =
    'This action cannot be undone. Make sure to have removed the key from any live integrations first.'

export function keyExpirationOptions(currentExpiresAt: string | null): LemonSelectOption<KeyExpirationOption>[] {
    return currentExpiresAt
        ? [
              {
                  value: 'keep',
                  label: `${isExpired(currentExpiresAt) ? 'Expired' : 'Expires'} ${dayjs(currentExpiresAt).format(EXPIRY_DATE_FORMAT)}`,
              },
              ...EXPIRATION_PRESETS,
          ]
        : EXPIRATION_PRESETS
}

/** Asks for the rolled key's expiry, the same way GitHub does when it regenerates a token. */
export function openRollKeyDialog(
    key: PersonalAPIKeyType,
    onRoll: (id: PersonalAPIKeyType['id'], expiresAt: string | null | undefined) => void,
    title: string = `Roll key "${key.label}"?`
): void {
    LemonDialog.openForm({
        title,
        description: 'This will generate a new key. The old key will immediately stop working.',
        initialValues: { expiration: key.expires_at ? '30' : 'never' },
        content: (
            <LemonField name="expiration" label="New key expires">
                <LemonSelect options={EXPIRATION_PRESETS} data-attr="personal-api-key-roll-expiration" />
            </LemonField>
        ),
        primaryButtonProps: { children: 'Roll', status: 'danger' },
        onSubmit: ({ expiration }) => onRoll(key.id, expiresAtForOption(expiration)),
    })
}

/** Offered from the edit modal of a key that still uses legacy hashing. */
export function openUpgradeHashingRollDialog(
    key: PersonalAPIKeyType,
    closeEditModal: () => void,
    rollKey: (id: PersonalAPIKeyType['id'], expiresAt: string | null | undefined) => void
): void {
    openRollKeyDialog(
        key,
        (id, expiresAt) => {
            // Close the edit modal first so the post-roll new key value
            // is shown via the table's standard roll confirmation flow.
            closeEditModal()
            rollKey(id, expiresAt)
        },
        'Roll key to upgrade hashing?'
    )
}

export function editingKeySubmitDisabledReason(
    editingKeyChanged: boolean,
    editingKey: EditingKeyFormValues
): string | undefined {
    return !editingKeyChanged
        ? 'No changes to save'
        : !editingKey.label
          ? 'Add a label'
          : !editingKey.scopes?.length
            ? 'Select at least one scope'
            : !editingKey.access_type
              ? 'Select access mode'
              : editingKey.access_type === 'organizations' && !editingKey.scoped_organizations?.length
                ? 'Select at least one organization'
                : editingKey.access_type === 'teams' && !editingKey.scoped_teams?.length
                  ? 'Select at least one project'
                  : undefined
}

export interface PersonalAPIKeyStatus {
    label: 'Expired' | 'Disabled' | 'Partial restrictions'
    severity: 'danger' | 'warning'
    tooltip: JSX.Element | string
}

/** The key's problem, if it has one. A healthy key returns null. */
export function personalAPIKeyStatus(
    key: PersonalAPIKeyType,
    keyDisabled: boolean,
    restrictedOrgs: OrganizationBasicType[],
    restrictedTeams: TeamBasicType[]
): PersonalAPIKeyStatus | null {
    const hasPartialRestrictions = (restrictedOrgs.length > 0 || restrictedTeams.length > 0) && !keyDisabled

    if (isExpired(key.expires_at)) {
        return {
            label: 'Expired',
            severity: 'danger',
            tooltip: 'This key has expired and no longer works. Edit it to set a new expiry, or delete it.',
        }
    }

    if (keyDisabled) {
        const orgNames = restrictedOrgs.map((org: any) => org.name)

        return {
            label: 'Disabled',
            severity: 'danger',
            tooltip:
                orgNames.length === 1 ? (
                    <span>
                        Organization <strong>{orgNames[0]}</strong> has restricted the use of personal API keys.
                    </span>
                ) : (
                    <span>
                        Organizations <strong>{orgNames.join(', ')}</strong> have restricted the use of personal API
                        keys.
                    </span>
                ),
        }
    }

    if (!hasPartialRestrictions) {
        return null
    }

    let tooltipMessage: JSX.Element = <span />

    if (restrictedTeams.length > 0) {
        const restrictedTeamNames = restrictedTeams.map((team: any) => team.name)
        const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

        if (restrictedOrgNames.length === 1 && restrictedTeamNames.length === 1) {
            tooltipMessage = (
                <span>
                    Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use of personal API keys.
                    This key will not work for project <strong>{restrictedTeamNames[0]}</strong>.
                </span>
            )
        } else if (restrictedOrgNames.length === 1) {
            tooltipMessage = (
                <span>
                    Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use of personal API keys.
                    This key will not work for projects: <strong>{restrictedTeamNames.join(', ')}</strong>.
                </span>
            )
        } else {
            tooltipMessage = (
                <span>
                    Multiple organizations have restricted personal API keys. This key will not work for projects:{' '}
                    <strong>{restrictedTeamNames.join(', ')}</strong>.
                </span>
            )
        }
    } else if (restrictedOrgs.length > 0) {
        const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

        tooltipMessage =
            restrictedOrgNames.length === 1 ? (
                <span>
                    Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use of personal API keys.
                </span>
            ) : (
                <span>
                    Organizations <strong>{restrictedOrgNames.join(', ')}</strong> have restricted the use of personal
                    API keys.
                </span>
            )
    }

    return { label: 'Partial restrictions', severity: 'warning', tooltip: tooltipMessage }
}

export interface PersonalAPIKeyAccessTag {
    id: string
    name: string
    restricted: boolean
}

/** The organizations or projects a key is scoped to, or null when it has access to everything. */
export function personalAPIKeyAccessTags(
    key: PersonalAPIKeyType,
    allOrganizations: OrganizationBasicType[],
    allTeams: TeamBasicType[] | null,
    restrictedOrgs: OrganizationBasicType[],
    restrictedTeams: TeamBasicType[]
): PersonalAPIKeyAccessTag[] | null {
    if (key?.scoped_organizations?.length) {
        return (
            key.scoped_organizations?.map((id) => {
                const org = allOrganizations.find((org) => org.id === id)
                return {
                    id,
                    name: org?.name || '',
                    restricted: restrictedOrgs.some((org: any) => org.id === id),
                }
            }) || []
        )
    } else if (key?.scoped_teams?.length) {
        return (
            key.scoped_teams?.map((id) => {
                const team = allTeams?.find((team) => team.id === id)
                return {
                    id: String(id),
                    name: team?.name || '',
                    restricted: restrictedTeams.some((team: any) => team.id === id),
                }
            }) || []
        )
    }
    return null
}
