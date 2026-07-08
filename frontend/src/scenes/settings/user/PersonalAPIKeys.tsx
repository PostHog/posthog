import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { IconInfo, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonModalProps,
    LemonSelect,
    LemonTableColumn,
    LemonTag,
    LemonTextArea,
    Tooltip,
} from '@posthog/lemon-ui'

import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { API_KEY_SCOPE_PRESETS, MAX_API_KEYS_PER_USER } from 'lib/scopes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { PersonalAPIKeyType } from '~/types'

import { APIKeyTable } from '../shared/APIKeyTable'
import { ScopeAccessRow } from '../shared/ScopeAccessRow'
import { personalAPIKeysLogic } from './personalAPIKeysLogic'
import ScopeAccessSelector from './scopes/ScopeAccessSelector'

interface EditKeyModalProps {
    zIndex?: LemonModalProps['zIndex']
}

export function EditKeyModal({ zIndex }: EditKeyModalProps): JSX.Element {
    const {
        editingKeyId,
        isEditingKeySubmitting,
        editingKeyChanged,
        formScopeRadioValues,
        allAccessSelected,
        isEditingKeyLegacy,
        editingKey,
        allTeams,
        allOrganizations,
        filteredScopes,
        searchTerm,
        isDescriptionFieldVisible,
    } = useValues(personalAPIKeysLogic)
    const {
        setEditingKeyId,
        setScopeRadioValue,
        submitEditingKey,
        resetScopes,
        setSearchTerm,
        rollKey,
        showDescriptionField,
    } = useActions(personalAPIKeysLogic)
    const { isCloudOrDev } = useValues(preflightLogic)

    const isNew = editingKeyId === 'new'

    const submitDisabledReason = !editingKeyChanged
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

    return (
        <Form logic={personalAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={`${isNew ? 'Create' : 'Edit'} personal API key`}
                onClose={() => setEditingKeyId(null)}
                isOpen={!!editingKeyId}
                width="40rem"
                hasUnsavedInput={editingKeyChanged}
                zIndex={zIndex}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setEditingKeyId(null)}>
                            Cancel
                        </LemonButton>

                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isEditingKeySubmitting}
                            disabledReason={submitDisabledReason}
                            onClick={() => submitEditingKey()}
                        >
                            {isNew ? 'Create key' : 'Save key'}
                        </LemonButton>
                    </>
                }
            >
                <>
                    {!isNew && isEditingKeyLegacy && (
                        <LemonBanner
                            type="warning"
                            className="mb-4"
                            action={{
                                children: 'Roll key',
                                onClick: () => {
                                    if (editingKeyId) {
                                        const id = editingKeyId
                                        LemonDialog.open({
                                            title: 'Roll key to upgrade hashing?',
                                            description:
                                                'This will generate a new key. The old key will immediately stop working.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Roll',
                                                type: 'primary',
                                                onClick: () => {
                                                    // Close the edit modal first so the post-roll new key value
                                                    // is shown via the table's standard roll confirmation flow.
                                                    setEditingKeyId(null)
                                                    rollKey(id)
                                                },
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'secondary',
                                            },
                                        })
                                    }
                                },
                            }}
                        >
                            <b>This key uses legacy hashing.</b> Roll it to upgrade to the new secure format. Your
                            existing key value will become invalid.
                        </LemonBanner>
                    )}
                    <LemonField name="label" label="Label">
                        <LemonInput placeholder='For example "Reports bot" or "Zapier"' maxLength={40} />
                    </LemonField>
                    {isDescriptionFieldVisible ? (
                        <LemonField name="description" label="Description" showOptional className="mt-2">
                            <LemonTextArea
                                placeholder="What is this key used for, and where? For example a link to the integration using it"
                                maxLength={1000}
                                minRows={2}
                                data-attr="personal-api-key-description"
                            />
                        </LemonField>
                    ) : (
                        <div className="mt-1">
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                icon={<IconPlus />}
                                onClick={() => showDescriptionField()}
                                data-attr="personal-api-key-add-description"
                            >
                                Add description
                            </LemonButton>
                        </div>
                    )}
                    <ScopeAccessSelector
                        accessType={editingKey.access_type}
                        organizations={allOrganizations}
                        teams={allTeams ?? undefined}
                    />
                    <div className="flex items-center justify-between mt-4 mb-2">
                        <LemonLabel>Scopes</LemonLabel>
                        <LemonField name="preset">
                            <LemonSelect
                                size="small"
                                placeholder="Select preset"
                                options={API_KEY_SCOPE_PRESETS.filter((preset) => !preset.isCloudOnly || isCloudOrDev)}
                                dropdownMatchSelectWidth={false}
                                dropdownPlacement="bottom-end"
                            />
                        </LemonField>
                    </div>

                    <LemonField name="scopes">
                        {({ error }) => (
                            <>
                                <p className="mb-0">
                                    Personal API keys are scoped to limit what actions they are able to do. We highly
                                    recommend you only give the key the permissions it needs to do its job. You can add
                                    or revoke scopes later.
                                </p>
                                <p className="m-0">
                                    Your personal API key can never take actions for which your account is missing
                                    permissions.
                                </p>

                                {error && (
                                    <div className="text-danger flex items-center gap-1 text-sm">
                                        <IconErrorOutline className="text-xl" /> {error}
                                    </div>
                                )}

                                {allAccessSelected ? (
                                    <LemonBanner
                                        type="warning"
                                        action={{
                                            children: 'Reset',
                                            onClick: () => resetScopes(),
                                        }}
                                    >
                                        <b>This personal API key has full access to all supported endpoints!</b> We
                                        highly recommend scoping this to only what it needs.
                                    </LemonBanner>
                                ) : (
                                    <div>
                                        <LemonInput
                                            type="search"
                                            placeholder="Search scopes..."
                                            value={searchTerm}
                                            onChange={setSearchTerm}
                                            className="mb-2"
                                            size="small"
                                        />
                                        <div className="max-h-[50vh] overflow-y-auto">
                                            {filteredScopes.length === 0 ? (
                                                <div className="text-muted text-sm py-2">
                                                    No scopes match "{searchTerm}"
                                                </div>
                                            ) : (
                                                filteredScopes.map(
                                                    ({
                                                        key,
                                                        objectName,
                                                        disabledActions,
                                                        warnings,
                                                        disabledWhenProjectScoped,
                                                        info,
                                                    }) => {
                                                        const disabledDueToProjectScope =
                                                            disabledWhenProjectScoped &&
                                                            editingKey.access_type === 'teams'
                                                        const selectedScopeAction = formScopeRadioValues[key]
                                                        const warningScopeAction =
                                                            selectedScopeAction === 'read' ||
                                                            selectedScopeAction === 'write'
                                                                ? selectedScopeAction
                                                                : null
                                                        return (
                                                            <ScopeAccessRow
                                                                key={key}
                                                                label={objectName}
                                                                info={info}
                                                                muted={disabledDueToProjectScope}
                                                                value={formScopeRadioValues[key] ?? 'none'}
                                                                onChange={(value) => setScopeRadioValue(key, value)}
                                                                readDisabledReason={
                                                                    disabledActions?.includes('read')
                                                                        ? 'Does not apply to this resource'
                                                                        : disabledDueToProjectScope
                                                                          ? 'Not available for project scoped keys'
                                                                          : undefined
                                                                }
                                                                writeDisabledReason={
                                                                    disabledActions?.includes('write')
                                                                        ? 'Does not apply to this resource'
                                                                        : disabledDueToProjectScope
                                                                          ? 'Not available for project scoped keys'
                                                                          : undefined
                                                                }
                                                                warning={
                                                                    warningScopeAction
                                                                        ? warnings?.[warningScopeAction]
                                                                        : undefined
                                                                }
                                                            />
                                                        )
                                                    }
                                                )
                                            )}
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </LemonField>
                </>
            </LemonModal>
        </Form>
    )
}

type TagListProps = { onMoreClick?: () => void; tags: string[] }

export function TagList({ tags, onMoreClick }: TagListProps): JSX.Element {
    return (
        <span className="flex flex-wrap gap-1">
            {tags.slice(0, 4).map((x) => (
                <>
                    <LemonTag key={x}>{x}</LemonTag>
                </>
            ))}
            {tags.length > 4 && (
                <Tooltip title={tags.slice(4).join(', ')}>
                    <LemonTag onClick={onMoreClick} forceClickable={!!onMoreClick}>
                        +{tags.length - 4} more
                    </LemonTag>
                </Tooltip>
            )}
        </span>
    )
}

type TagListWithRestrictionsProps = {
    onMoreClick: () => void
    tags: Array<{ id: string; name: string; restricted: boolean }>
}

export function TagListWithRestrictions({ tags, onMoreClick }: TagListWithRestrictionsProps): JSX.Element {
    return (
        <span className="flex flex-wrap gap-1 items-center">
            {tags.slice(0, 4).map((tag) => (
                <LemonTag key={tag.id} className={tag.restricted ? 'line-through opacity-60' : ''}>
                    {tag.name}
                </LemonTag>
            ))}
            {tags.length > 4 && (
                <Tooltip
                    title={tags
                        .slice(4)
                        .map((tag) => tag.name)
                        .join(', ')}
                >
                    <LemonTag onClick={onMoreClick} forceClickable>
                        +{tags.length - 4} more
                    </LemonTag>
                </Tooltip>
            )}
        </span>
    )
}

function PersonalAPIKeysTable(): JSX.Element {
    const {
        keys,
        keysLoading,
        allOrganizations,
        allTeams,
        isPersonalApiKeyIdDisabled,
        getRestrictedOrganizationsForKey,
        getRestrictedTeamsForKey,
    } = useValues(personalAPIKeysLogic)
    const { deleteKey, loadKeys, setEditingKeyId, rollKey } = useActions(personalAPIKeysLogic)

    useEffect(() => loadKeys(), [loadKeys])

    const statusColumn: LemonTableColumn<PersonalAPIKeyType, any> = {
        title: 'Status',
        key: 'status',
        dataIndex: 'id',
        render: function RenderStatus(_, key) {
            const keyDisabled = isPersonalApiKeyIdDisabled(key.id)
            const restrictedOrgs = getRestrictedOrganizationsForKey(key.id)
            const restrictedTeams = getRestrictedTeamsForKey(key.id)
            const hasPartialRestrictions = (restrictedOrgs.length > 0 || restrictedTeams.length > 0) && !keyDisabled

            const legacyTag = key.is_legacy_hashing ? (
                <Tooltip title="This key uses legacy hashing. Roll or delete it to upgrade.">
                    <LemonTag type="caution">Legacy</LemonTag>
                </Tooltip>
            ) : null

            let statusTag: JSX.Element | null = null

            if (keyDisabled) {
                const orgNames = restrictedOrgs.map((org: any) => org.name)

                statusTag = (
                    <Tooltip
                        title={
                            orgNames.length === 1 ? (
                                <span>
                                    Organization <strong>{orgNames[0]}</strong> has restricted the use of personal API
                                    keys.
                                </span>
                            ) : (
                                <span>
                                    Organizations <strong>{orgNames.join(', ')}</strong> have restricted the use of
                                    personal API keys.
                                </span>
                            )
                        }
                    >
                        <LemonTag type="danger">Disabled</LemonTag>
                    </Tooltip>
                )
            } else if (hasPartialRestrictions) {
                let tooltipMessage: JSX.Element = <span />

                if (restrictedTeams.length > 0) {
                    const restrictedTeamNames = restrictedTeams.map((team: any) => team.name)
                    const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

                    if (restrictedOrgNames.length === 1 && restrictedTeamNames.length === 1) {
                        tooltipMessage = (
                            <span>
                                Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use of personal
                                API keys. This key will not work for project <strong>{restrictedTeamNames[0]}</strong>.
                            </span>
                        )
                    } else if (restrictedOrgNames.length === 1) {
                        tooltipMessage = (
                            <span>
                                Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use of personal
                                API keys. This key will not work for projects:{' '}
                                <strong>{restrictedTeamNames.join(', ')}</strong>.
                            </span>
                        )
                    } else {
                        tooltipMessage = (
                            <span>
                                Multiple organizations have restricted personal API keys. This key will not work for
                                projects: <strong>{restrictedTeamNames.join(', ')}</strong>.
                            </span>
                        )
                    }
                } else if (restrictedOrgs.length > 0) {
                    const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

                    tooltipMessage =
                        restrictedOrgNames.length === 1 ? (
                            <span>
                                Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use of personal
                                API keys.
                            </span>
                        ) : (
                            <span>
                                Organizations <strong>{restrictedOrgNames.join(', ')}</strong> have restricted the use
                                of personal API keys.
                            </span>
                        )
                }

                statusTag = (
                    <Tooltip title={tooltipMessage}>
                        <LemonTag type="warning">Partial restrictions</LemonTag>
                    </Tooltip>
                )
            }

            if (statusTag && legacyTag) {
                return (
                    <span className="flex flex-wrap gap-1">
                        {statusTag}
                        {legacyTag}
                    </span>
                )
            }

            return statusTag ?? legacyTag ?? <LemonTag type="success">Active</LemonTag>
        },
    }

    const accessColumn: LemonTableColumn<PersonalAPIKeyType, any> = {
        title: 'Organization & project access',
        key: 'access',
        dataIndex: 'id',
        render: function RenderAccess(_, key) {
            const restrictedOrgs = getRestrictedOrganizationsForKey(key.id)
            const restrictedTeams = getRestrictedTeamsForKey(key.id)

            if (key?.scoped_organizations?.length) {
                const orgTags =
                    key.scoped_organizations?.map((id) => {
                        const org = allOrganizations.find((org) => org.id === id)
                        return {
                            id,
                            name: org?.name || '',
                            restricted: restrictedOrgs.some((org: any) => org.id === id),
                        }
                    }) || []

                return <TagListWithRestrictions tags={orgTags} onMoreClick={() => setEditingKeyId(key.id)} />
            } else if (key?.scoped_teams?.length) {
                const teamTags =
                    key.scoped_teams?.map((id) => {
                        const team = allTeams?.find((team) => team.id === id)
                        return {
                            id: String(id),
                            name: team?.name || '',
                            restricted: restrictedTeams.some((team: any) => team.id === id),
                        }
                    }) || []

                return <TagListWithRestrictions tags={teamTags} onMoreClick={() => setEditingKeyId(key.id)} />
            }
            return <LemonTag type="warning">All access</LemonTag>
        },
    }

    return (
        <>
            {keys.some((key) => key.is_legacy_hashing) && (
                <LemonBanner type="info" className="mt-2">
                    Some of your personal API keys use legacy hashing. Consider rolling or deleting them to upgrade.
                </LemonBanner>
            )}
            <APIKeyTable<PersonalAPIKeyType>
                keys={keys}
                loading={keysLoading}
                noun="personal API key"
                onEdit={setEditingKeyId}
                onRoll={rollKey}
                onDelete={deleteKey}
                showActions
                rowClassName={(key) => (isPersonalApiKeyIdDisabled(key.id) ? 'opacity-50' : '')}
                deleteDescription="This action cannot be undone. Make sure to have removed the key from any live integrations first."
                renderLabel={(key) => (
                    <div className="flex flex-col">
                        <Link
                            subtle
                            className="text-left font-semibold truncate"
                            onClick={() => setEditingKeyId(key.id)}
                        >
                            {key.label}
                        </Link>
                        {key.description && (
                            <Tooltip title={key.description}>
                                <span className="text-muted text-xs truncate max-w-60">{key.description}</span>
                            </Tooltip>
                        )}
                    </div>
                )}
                renderMaskValue={(key) =>
                    key.mask_value ? (
                        <span className="font-mono ph-no-capture">{key.mask_value}</span>
                    ) : (
                        <Tooltip title="This key was created before the introduction of previews" placement="right">
                            <span className="inline-flex items-center gap-1 cursor-default">
                                <span>No preview</span>
                                <IconInfo className="text-base" />
                            </span>
                        </Tooltip>
                    )
                }
                renderScopes={(key) =>
                    key.scopes[0] === '*' ? (
                        <LemonTag type="warning">All access</LemonTag>
                    ) : (
                        <TagList tags={key.scopes} onMoreClick={() => setEditingKeyId(key.id)} />
                    )
                }
                extraColumnsAfterLabel={[statusColumn]}
                extraColumnsAfterScopes={[accessColumn]}
            />
        </>
    )
}

export function PersonalAPIKeys(): JSX.Element {
    const { keys, canUsePersonalApiKeys } = useValues(personalAPIKeysLogic)
    const { setEditingKeyId } = useActions(personalAPIKeysLogic)

    return (
        <>
            <LemonButton
                type="primary"
                icon={<IconPlus />}
                onClick={() => setEditingKeyId('new')}
                disabledReason={
                    !canUsePersonalApiKeys
                        ? 'Your organization does not allow members using personal API keys.'
                        : keys.length >= MAX_API_KEYS_PER_USER
                          ? `You can only have ${MAX_API_KEYS_PER_USER} personal API keys. Remove an existing key before creating a new one.`
                          : false
                }
            >
                Create personal API key
            </LemonButton>

            <PersonalAPIKeysTable />

            <EditKeyModal />
        </>
    )
}
