import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { ReactNode, useEffect } from 'react'

import { IconInfo, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
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
import { Button } from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ScopeAccessGroup } from 'lib/components/ScopeAccessRow/ScopeAccessGroup'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { API_KEY_SCOPE_PRESETS, DEFAULT_MAX_API_KEYS_PER_USER } from 'lib/scopes'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { userLogic } from 'scenes/userLogic'

import { PersonalAPIKeyType } from '~/types'

import { APIKeyTable } from '../shared/APIKeyTable'
import { expiresAtForOption, isExpired, personalAPIKeysLogic } from './personalAPIKeysLogic'
import {
    DELETE_KEY_DESCRIPTION,
    EXPIRY_DATE_FORMAT,
    EXPIRY_TIME_FORMAT,
    LEGACY_HASHING_TOOLTIP,
    editingKeySubmitDisabledReason,
    keyExpirationOptions,
    openRollKeyDialog,
    openUpgradeHashingRollDialog,
    personalAPIKeyAccessTags,
    personalAPIKeyStatus,
} from './personalAPIKeysUtils'
import { QuillEditKeyModal } from './QuillEditKeyModal'
import { QuillPersonalAPIKeysTable } from './QuillPersonalAPIKeysTable'
import ScopeAccessSelector from './scopes/ScopeAccessSelector'
import { ScopeGroupSummary } from './scopes/ScopeGroupSummary'

interface EditKeyModalProps {
    zIndex?: LemonModalProps['zIndex']
}

export function EditKeyModal({ zIndex }: EditKeyModalProps): JSX.Element {
    const {
        editingKeyId,
        isEditingKeySubmitting,
        editingKeyChanged,
        allAccessSelected,
        isEditingKeyLegacy,
        editingKey,
        allTeams,
        allOrganizations,
        filteredScopeGroups,
        searchTerm,
        isDescriptionFieldVisible,
        keys,
    } = useValues(personalAPIKeysLogic)
    const {
        setEditingKeyId,
        setScopeRadioValue,
        setScopeGroupAccess,
        submitEditingKey,
        resetScopes,
        setSearchTerm,
        rollKey,
        showDescriptionField,
    } = useActions(personalAPIKeysLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const quillSurface = useQuillSurface()

    const isNew = editingKeyId === 'new'
    const editingKeyRecord = isNew ? undefined : keys.find((key) => key.id === editingKeyId)

    const submitDisabledReason = editingKeySubmitDisabledReason(editingKeyChanged, editingKey)

    const closeModal = (): void => setEditingKeyId(null)

    const rollLegacyKey = (): void => {
        if (editingKeyRecord) {
            openUpgradeHashingRollDialog(editingKeyRecord, () => setEditingKeyId(null), rollKey)
        }
    }

    const scopePresets = API_KEY_SCOPE_PRESETS.filter((preset) => !preset.isCloudOnly || isCloudOrDev)

    if (quillSurface) {
        return (
            <QuillEditKeyModal
                isNew={isNew}
                isOpen={!!editingKeyId}
                onClose={closeModal}
                hasUnsavedInput={editingKeyChanged}
                isSubmitting={isEditingKeySubmitting}
                submitDisabledReason={submitDisabledReason}
                onSubmit={() => submitEditingKey()}
                showLegacyHashingNotice={!isNew && isEditingKeyLegacy}
                onRollLegacyKey={rollLegacyKey}
                isDescriptionFieldVisible={isDescriptionFieldVisible}
                onShowDescriptionField={() => showDescriptionField()}
                currentExpiresAt={editingKeyRecord?.expires_at ?? null}
                accessType={editingKey.access_type}
                organizations={allOrganizations}
                teams={allTeams ?? undefined}
                presets={scopePresets}
                allAccessSelected={allAccessSelected}
                onResetScopes={() => resetScopes()}
                searchTerm={searchTerm}
                onSearchTermChange={setSearchTerm}
                scopeGroups={filteredScopeGroups}
                onChangeScopeRow={setScopeRadioValue}
                onChangeScopeGroup={setScopeGroupAccess}
            />
        )
    }

    return (
        <Form logic={personalAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={`${isNew ? 'Create' : 'Edit'} personal API key`}
                onClose={closeModal}
                isOpen={!!editingKeyId}
                width="40rem"
                hasUnsavedInput={editingKeyChanged}
                zIndex={zIndex}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeModal}>
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
                                onClick: rollLegacyKey,
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
                    <KeyExpirationField currentExpiresAt={editingKeyRecord?.expires_at ?? null} />
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
                                options={scopePresets}
                                dropdownMatchSelectWidth={false}
                                dropdownPlacement="bottom-end"
                            />
                        </LemonField>
                    </div>

                    <LemonField name="scopes">
                        {() => (
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
                                        {filteredScopeGroups.length === 0 ? (
                                            <div className="text-muted text-sm py-2">
                                                No scopes match "{searchTerm}"
                                            </div>
                                        ) : (
                                            filteredScopeGroups.map((group) => (
                                                <ScopeAccessGroup
                                                    // A search opens every group, and clearing it closes them again.
                                                    key={`${group.label}-${searchTerm !== ''}`}
                                                    group={group}
                                                    defaultOpen={searchTerm !== ''}
                                                    onChangeRow={setScopeRadioValue}
                                                    onChangeGroup={setScopeGroupAccess}
                                                    dataAttrPrefix="personal-api-key-scope-group"
                                                />
                                            ))
                                        )}
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

function KeyExpirationField({ currentExpiresAt }: { currentExpiresAt: string | null }): JSX.Element {
    const { editingKey } = useValues(personalAPIKeysLogic)

    const options = keyExpirationOptions(currentExpiresAt)

    const expiresAt = expiresAtForOption(editingKey.expiration)

    return (
        <div className="mt-4">
            <LemonField name="expiration" label="Expiration">
                <LemonSelect options={options} data-attr="personal-api-key-expiration" />
            </LemonField>
            {expiresAt !== undefined && (
                <p className="text-secondary text-xs mt-1 mb-0">
                    {expiresAt ? (
                        <>
                            <span>The key stops working on </span>
                            <TZLabel time={expiresAt} formatDate={EXPIRY_DATE_FORMAT} formatTime={EXPIRY_TIME_FORMAT} />
                            <span>.</span>
                        </>
                    ) : (
                        'The key keeps working until you delete it.'
                    )}
                </p>
            )}
        </div>
    )
}

type TagListProps = {
    onMoreClick?: () => void
    tags: string[]
    /** Content of the "+N more" tooltip. Defaults to the hidden tags, comma separated. */
    tooltip?: ReactNode
}

export function TagList({ tags, onMoreClick, tooltip }: TagListProps): JSX.Element {
    return (
        <span className="flex flex-wrap gap-1">
            {tags.slice(0, 4).map((x) => (
                <>
                    <LemonTag key={x}>{x}</LemonTag>
                </>
            ))}
            {tags.length > 4 && (
                <Tooltip title={tooltip ?? tags.slice(4).join(', ')}>
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
            const status = personalAPIKeyStatus(
                key,
                isPersonalApiKeyIdDisabled(key.id),
                getRestrictedOrganizationsForKey(key.id),
                getRestrictedTeamsForKey(key.id)
            )

            const legacyTag = key.is_legacy_hashing ? (
                <Tooltip title={LEGACY_HASHING_TOOLTIP}>
                    <LemonTag type="caution">Legacy</LemonTag>
                </Tooltip>
            ) : null

            const statusTag = status ? (
                <Tooltip title={status.tooltip}>
                    <LemonTag type={status.severity}>{status.label}</LemonTag>
                </Tooltip>
            ) : null

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
        title: 'Org & project access',
        key: 'access',
        dataIndex: 'id',
        render: function RenderAccess(_, key) {
            const accessTags = personalAPIKeyAccessTags(
                key,
                allOrganizations,
                allTeams,
                getRestrictedOrganizationsForKey(key.id),
                getRestrictedTeamsForKey(key.id)
            )

            if (accessTags) {
                return <TagListWithRestrictions tags={accessTags} onMoreClick={() => setEditingKeyId(key.id)} />
            }
            return <LemonTag type="warning">All access</LemonTag>
        },
    }

    const expiresColumn: LemonTableColumn<PersonalAPIKeyType, any> = {
        title: 'Expires',
        key: 'expiresAt',
        dataIndex: 'expires_at',
        sorter: (a, b) => {
            if (!a.expires_at || !b.expires_at) {
                return Number(!a.expires_at) - Number(!b.expires_at)
            }
            return dayjs(a.expires_at).valueOf() - dayjs(b.expires_at).valueOf()
        },
        render: function RenderExpiresAt(_, key) {
            if (!key.expires_at) {
                return <span className="text-secondary">Never</span>
            }
            return <TZLabel time={key.expires_at} formatDate={EXPIRY_DATE_FORMAT} formatTime={EXPIRY_TIME_FORMAT} />
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
                openRollDialog={(key) => openRollKeyDialog(key, rollKey)}
                onDelete={deleteKey}
                showActions
                rowClassName={(key) =>
                    isPersonalApiKeyIdDisabled(key.id) || isExpired(key.expires_at) ? 'opacity-50' : ''
                }
                deleteDescription={DELETE_KEY_DESCRIPTION}
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
                    key.local_dev_value ? (
                        <CopyToClipboardInline
                            description="personal API key"
                            tooltipMessage="Local development key. Its full value is shown because this instance has DEBUG and ALLOW_DEV_API_KEY_REVEAL set."
                            selectable
                            isValueSensitive
                            iconSize="xsmall"
                            className="font-mono text-xs max-w-60 whitespace-normal"
                        >
                            {key.local_dev_value}
                        </CopyToClipboardInline>
                    ) : key.mask_value ? (
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
                        <TagList
                            tags={key.scopes}
                            tooltip={<ScopeGroupSummary scopes={key.scopes} />}
                            onMoreClick={() => setEditingKeyId(key.id)}
                        />
                    )
                }
                extraColumnsAfterLabel={[statusColumn]}
                extraColumnsAfterScopes={[accessColumn, expiresColumn]}
            />
        </>
    )
}

export function PersonalAPIKeys(): JSX.Element {
    const { keys, canUsePersonalApiKeys } = useValues(personalAPIKeysLogic)
    const { setEditingKeyId } = useActions(personalAPIKeysLogic)
    const { user } = useValues(userLogic)
    const keysLimit = user?.personal_api_keys_limit ?? DEFAULT_MAX_API_KEYS_PER_USER
    const todayRailNav = useQuillSurface()

    const createDisabledReason = !canUsePersonalApiKeys
        ? 'Your organization does not allow members using personal API keys.'
        : keys.length >= keysLimit
          ? `You can only have ${keysLimit} personal API keys. Remove an existing key before creating a new one.`
          : false

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div>
                    <Button
                        variant="primary"
                        onClick={() => setEditingKeyId('new')}
                        disabledReason={createDisabledReason || null}
                    >
                        <IconPlus />
                        Create personal API key
                    </Button>
                </div>
                <QuillPersonalAPIKeysTable />
                <EditKeyModal />
            </div>
        )
    }

    return (
        <>
            <LemonButton
                type="primary"
                icon={<IconPlus />}
                onClick={() => setEditingKeyId('new')}
                disabledReason={createDisabledReason}
            >
                Create personal API key
            </LemonButton>

            <PersonalAPIKeysTable />

            <EditKeyModal />
        </>
    )
}
