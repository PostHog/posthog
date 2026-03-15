import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Fragment, useEffect, useMemo } from 'react'

import { IconBug, IconGear, IconGraph, IconPlug, IconToggle, IconWarning } from '@posthog/icons'
import { IconEllipsis, IconInfo, IconMagicWand, IconPlus, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonCard,
    LemonDialog,
    LemonInput,
    LemonMenu,
    LemonModal,
    LemonModalProps,
    LemonSegmentedButton,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { API_KEY_INTENT_TILES, MAX_API_KEYS_PER_USER } from 'lib/scopes'
import { detailedTime, humanFriendlyDetailedTime } from 'lib/utils'

import { APIKeyWizardStep, personalAPIKeysLogic, ScopeGroupWithCounts } from './personalAPIKeysLogic'
import ScopeAccessSelector from './scopes/ScopeAccessSelector'

const INTENT_TILE_ICONS: Record<string, JSX.Element> = {
    read_data: <IconGraph className="text-2xl" />,
    feature_releases: <IconToggle className="text-2xl" />,
    integrations: <IconPlug className="text-2xl" />,
    monitor_debug: <IconBug className="text-2xl" />,
    build_ai: <IconMagicWand className="text-2xl" />,
    admin: <IconGear className="text-2xl" />,
}

interface EditKeyModalProps {
    zIndex?: LemonModalProps['zIndex']
}

function ScopeRow({
    scopeKey,
    objectName,
    disabledActions,
    warnings,
    disabledWhenProjectScoped,
    info,
    accessType,
    formScopeRadioValues,
    setScopeRadioValue,
}: {
    scopeKey: string
    objectName: string
    disabledActions?: ('read' | 'write')[]
    warnings?: Partial<Record<'read' | 'write', string | JSX.Element>>
    disabledWhenProjectScoped?: boolean
    info?: string | JSX.Element
    accessType?: string
    formScopeRadioValues: Record<string, string>
    setScopeRadioValue: (key: string, action: string) => void
}): JSX.Element {
    const disabledDueToProjectScope = disabledWhenProjectScoped && accessType === 'teams'
    const selectedScopeAction = formScopeRadioValues[scopeKey]
    const warningScopeAction =
        selectedScopeAction === 'read' || selectedScopeAction === 'write' ? selectedScopeAction : null

    return (
        <Fragment>
            <div className="flex items-center justify-between gap-2 min-h-8 group">
                <div className={clsx('flex items-center gap-1', disabledDueToProjectScope && 'text-muted')}>
                    <b className="transition-colors group-hover:text-highlight">{objectName}</b>
                    {info ? (
                        <Tooltip title={info}>
                            <IconInfo className="text-secondary text-base" />
                        </Tooltip>
                    ) : null}
                </div>
                <LemonSegmentedButton
                    onChange={(value) => setScopeRadioValue(scopeKey, value)}
                    value={formScopeRadioValues[scopeKey] ?? 'none'}
                    options={[
                        { label: 'No access', value: 'none' },
                        {
                            label: 'Read',
                            value: 'read',
                            disabledReason: disabledActions?.includes('read')
                                ? 'Does not apply to this resource'
                                : disabledDueToProjectScope
                                  ? 'Not available for project scoped keys'
                                  : undefined,
                        },
                        {
                            label: 'Write',
                            value: 'write',
                            disabledReason: disabledActions?.includes('write')
                                ? 'Does not apply to this resource'
                                : disabledDueToProjectScope
                                  ? 'Not available for project scoped keys'
                                  : undefined,
                        },
                    ]}
                    size="xsmall"
                />
            </div>
            {warningScopeAction && warnings?.[warningScopeAction] && (
                <div className="flex items-start gap-2 text-xs italic pb-2">
                    <IconWarning className="text-base text-secondary mt-0.5" />
                    <span>{warnings[warningScopeAction]}</span>
                </div>
            )}
        </Fragment>
    )
}

function WizardStepBasics(): JSX.Element {
    const { editingKey, allTeams, allOrganizations, selectedScopesList, allAccessSelected } =
        useValues(personalAPIKeysLogic)

    return (
        <div className="space-y-4">
            <LemonField name="label" label="Label">
                <LemonInput placeholder='For example "Reports bot" or "Zapier"' maxLength={40} autoFocus />
            </LemonField>
            <ScopeAccessSelector
                accessType={editingKey.access_type}
                organizations={allOrganizations}
                teams={allTeams ?? undefined}
            />
            <div className="border rounded p-3 bg-bg-light">
                <div className="font-semibold text-xs text-muted mb-1">THIS KEY WILL HAVE ACCESS TO</div>
                {allAccessSelected ? (
                    <div className="text-warning text-sm font-medium">All scopes (full access)</div>
                ) : selectedScopesList.length === 0 ? (
                    <div className="text-muted text-sm">No scopes selected</div>
                ) : (
                    <div className="max-h-32 overflow-y-auto text-xs space-y-0.5">
                        {selectedScopesList.map((scope) => (
                            <div key={scope.key} className="flex items-center gap-1">
                                <span className={scope.action === 'write' ? 'text-warning-dark' : 'text-default'}>
                                    {scope.key}:{scope.action}
                                </span>
                                {scope.description && (
                                    <Tooltip title={scope.description}>
                                        <IconInfo className="text-muted text-xs" />
                                    </Tooltip>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

function WizardStepIntent(): JSX.Element {
    const { selectedIntentTiles } = useValues(personalAPIKeysLogic)
    const { toggleIntentTile, setWizardStep, setEditingKeyValue } = useActions(personalAPIKeysLogic)

    return (
        <div className="space-y-4">
            <div>
                <h3 className="font-semibold mb-1">What's this key for?</h3>
                <p className="text-muted text-sm m-0">
                    Select one or more use cases. We'll pre-configure the right scopes for you.
                </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
                {API_KEY_INTENT_TILES.map((tile) => {
                    const selected = selectedIntentTiles.includes(tile.key)
                    return (
                        <LemonCard
                            key={tile.key}
                            hoverEffect
                            focused={selected}
                            onClick={() => toggleIntentTile(tile.key)}
                            className="!p-4"
                        >
                            <div className="flex items-start gap-3">
                                <div className="text-muted-alt mt-0.5">{INTENT_TILE_ICONS[tile.key]}</div>
                                <div>
                                    <div className="font-semibold text-sm">{tile.title}</div>
                                    <div className="text-muted text-xs mt-0.5">{tile.description}</div>
                                </div>
                            </div>
                        </LemonCard>
                    )
                })}
            </div>
            <div className="flex items-center gap-3 text-sm">
                <Link subtle onClick={() => setWizardStep(APIKeyWizardStep.Review)}>
                    Skip to custom configuration
                </Link>
                <span className="text-muted">or</span>
                <Link
                    subtle
                    onClick={() => {
                        setEditingKeyValue('scopes', ['*'])
                        setWizardStep(APIKeyWizardStep.Review)
                    }}
                >
                    <span className="text-warning">Grant all access</span>
                </Link>
            </div>
        </div>
    )
}

function SelectedScopesSummary(): JSX.Element {
    const { selectedScopesList } = useValues(personalAPIKeysLogic)
    const { setScopeRadioValue } = useActions(personalAPIKeysLogic)

    return (
        <div className="border-l pl-3 h-full flex flex-col">
            <div className="font-bold text-xs mb-1">
                {selectedScopesList.length} SCOPE{selectedScopesList.length !== 1 ? 'S' : ''} SELECTED
            </div>
            {selectedScopesList.length === 0 ? (
                <div className="text-muted text-xs">Add permissions from the left.</div>
            ) : (
                <div className="overflow-y-auto flex-1 text-xs space-y-0.5">
                    {selectedScopesList.map((scope) => (
                        <div key={scope.key} className="flex items-center gap-1 group">
                            <Tooltip title={scope.description}>
                                <span
                                    className={clsx(
                                        'truncate',
                                        scope.action === 'write' ? 'text-warning-dark' : 'text-default'
                                    )}
                                >
                                    {scope.key}:{scope.action}
                                </span>
                            </Tooltip>
                            <LemonButton
                                icon={<IconX className="h-3.5 w-3.5" />}
                                size="xsmall"
                                className="shrink-0 opacity-0 group-hover:opacity-100"
                                onClick={() => setScopeRadioValue(scope.key, 'none')}
                            />
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function WizardStepReview(): JSX.Element {
    const { editingKeyId, formScopeRadioValues, allAccessSelected, editingKey, groupedScopes, searchTerm } =
        useValues(personalAPIKeysLogic)
    const { setScopeRadioValue, resetScopes, setSearchTerm } = useActions(personalAPIKeysLogic)

    const isNew = editingKeyId === 'new'

    // Auto-expand groups that have enabled scopes
    const defaultActiveKeys = useMemo(
        () => groupedScopes.filter((g) => g.enabledCount > 0).map((g) => g.key),
        // Only compute once on mount
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    )

    return (
        <LemonField name="scopes">
            {({ error }) => (
                <div className="space-y-2">
                    {!isNew && (
                        <div className="flex items-center gap-2 mb-2">
                            <LemonField name="label" label="Label" className="flex-1">
                                <LemonInput maxLength={40} />
                            </LemonField>
                        </div>
                    )}

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
                            <b>This API key has full access to all supported endpoints!</b> We highly recommend scoping
                            this to only what it needs.
                        </LemonBanner>
                    ) : (
                        <div className="flex gap-3 max-h-[50vh]">
                            <div className="flex-[3] overflow-y-auto space-y-2 min-w-0">
                                <LemonInput
                                    type="search"
                                    placeholder="Search scopes..."
                                    value={searchTerm}
                                    onChange={setSearchTerm}
                                    size="small"
                                />
                                {groupedScopes.length === 0 ? (
                                    <div className="text-muted text-sm py-2">No scopes match "{searchTerm}"</div>
                                ) : (
                                    <LemonCollapse
                                        multiple
                                        defaultActiveKeys={defaultActiveKeys}
                                        size="small"
                                        panels={groupedScopes.map((group: ScopeGroupWithCounts) => ({
                                            key: group.key,
                                            header: (
                                                <div className="flex items-center gap-2 w-full">
                                                    <span>{group.label}</span>
                                                    <LemonTag
                                                        size="small"
                                                        type={group.enabledCount > 0 ? 'primary' : 'muted'}
                                                    >
                                                        {group.enabledCount}/{group.totalCount}
                                                    </LemonTag>
                                                </div>
                                            ),
                                            content: (
                                                <div className="py-1 px-2">
                                                    {group.filteredScopes.map((scope) => (
                                                        <ScopeRow
                                                            key={scope.key}
                                                            scopeKey={scope.key}
                                                            objectName={scope.objectName}
                                                            disabledActions={scope.disabledActions}
                                                            warnings={scope.warnings}
                                                            disabledWhenProjectScoped={scope.disabledWhenProjectScoped}
                                                            info={scope.description ?? scope.info}
                                                            accessType={editingKey.access_type}
                                                            formScopeRadioValues={formScopeRadioValues}
                                                            setScopeRadioValue={setScopeRadioValue}
                                                        />
                                                    ))}
                                                </div>
                                            ),
                                        }))}
                                    />
                                )}
                            </div>
                            <div className="flex-[2] min-w-0">
                                <SelectedScopesSummary />
                            </div>
                        </div>
                    )}
                </div>
            )}
        </LemonField>
    )
}

function WizardFooter(): JSX.Element {
    const { wizardStep, editingKeyId, isEditingKeySubmitting, editingKeyChanged, canProceedFromBasics, editingKey } =
        useValues(personalAPIKeysLogic)
    const { setEditingKeyId, goToNextStep, goToPreviousStep, submitEditingKey } = useActions(personalAPIKeysLogic)

    const isNew = editingKeyId === 'new'

    if (wizardStep === APIKeyWizardStep.Intent) {
        return (
            <>
                <LemonButton type="secondary" onClick={() => setEditingKeyId(null)}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" onClick={goToNextStep}>
                    Next
                </LemonButton>
            </>
        )
    }

    if (wizardStep === APIKeyWizardStep.Review) {
        return (
            <>
                {isNew ? (
                    <LemonButton type="secondary" onClick={goToPreviousStep}>
                        Back
                    </LemonButton>
                ) : (
                    <LemonButton type="secondary" onClick={() => setEditingKeyId(null)}>
                        Cancel
                    </LemonButton>
                )}
                {isNew ? (
                    <LemonButton type="primary" onClick={goToNextStep}>
                        Next
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isEditingKeySubmitting}
                        disabled={!editingKeyChanged}
                        onClick={() => submitEditingKey()}
                    >
                        Save key
                    </LemonButton>
                )}
            </>
        )
    }

    // Basics step (final step for new keys)
    return (
        <>
            <LemonButton type="secondary" onClick={goToPreviousStep}>
                Back
            </LemonButton>
            <LemonButton
                type="primary"
                htmlType="submit"
                loading={isEditingKeySubmitting}
                onClick={() => submitEditingKey()}
                disabledReason={
                    !editingKey.label?.trim()
                        ? 'Enter a label first'
                        : !editingKey.access_type
                          ? 'Select an access type'
                          : !canProceedFromBasics
                            ? 'Complete the required fields'
                            : undefined
                }
            >
                Create key
            </LemonButton>
        </>
    )
}

const WIZARD_STEP_TITLES: Record<APIKeyWizardStep, { create: string; edit: string }> = {
    [APIKeyWizardStep.Intent]: { create: "What's this key for?", edit: "What's this key for?" },
    [APIKeyWizardStep.Review]: { create: 'Review & customize scopes', edit: 'Edit scopes' },
    [APIKeyWizardStep.Basics]: { create: 'Name & access', edit: 'Edit personal API key' },
}

export function EditKeyModal({ zIndex }: EditKeyModalProps): JSX.Element {
    const { editingKeyId, editingKeyChanged, wizardStep } = useValues(personalAPIKeysLogic)
    const { setEditingKeyId } = useActions(personalAPIKeysLogic)

    const isNew = editingKeyId === 'new'
    const title = WIZARD_STEP_TITLES[wizardStep][isNew ? 'create' : 'edit']

    return (
        <Form logic={personalAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={title}
                onClose={() => setEditingKeyId(null)}
                isOpen={!!editingKeyId}
                width={wizardStep === APIKeyWizardStep.Review ? '56rem' : '40rem'}
                hasUnsavedInput={editingKeyChanged}
                zIndex={zIndex}
                footer={<WizardFooter />}
            >
                {wizardStep === APIKeyWizardStep.Intent && <WizardStepIntent />}
                {wizardStep === APIKeyWizardStep.Review && <WizardStepReview />}
                {wizardStep === APIKeyWizardStep.Basics && <WizardStepBasics />}
            </LemonModal>
        </Form>
    )
}

type TagListProps = { onMoreClick: () => void; tags: string[] }

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
                    <LemonTag onClick={onMoreClick}>+{tags.length - 4} more</LemonTag>
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
                    <LemonTag onClick={onMoreClick}>+{tags.length - 4} more</LemonTag>
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

    return (
        <LemonTable
            dataSource={keys}
            loading={keysLoading}
            loadingSkeletonRows={3}
            className="mt-4"
            nouns={['personal API key', 'personal API keys']}
            rowClassName={(key) => (isPersonalApiKeyIdDisabled(key.id) ? 'opacity-50' : '')}
            columns={[
                {
                    title: 'Label',
                    dataIndex: 'label',
                    key: 'label',
                    render: function RenderLabel(label, key) {
                        return (
                            <div className="flex flex-wrap gap-1 items-center">
                                <Link
                                    subtle
                                    className="text-left font-semibold truncate"
                                    onClick={() => setEditingKeyId(key.id)}
                                >
                                    {String(label)}
                                </Link>
                            </div>
                        )
                    },
                },
                {
                    title: 'Status',
                    key: 'status',
                    dataIndex: 'id',
                    render: function RenderStatus(_, key) {
                        const keyDisabled = isPersonalApiKeyIdDisabled(key.id)
                        const restrictedOrgs = getRestrictedOrganizationsForKey(key.id)
                        const restrictedTeams = getRestrictedTeamsForKey(key.id)
                        const hasPartialRestrictions =
                            (restrictedOrgs.length > 0 || restrictedTeams.length > 0) && !keyDisabled

                        if (keyDisabled) {
                            const orgNames = restrictedOrgs.map((org: any) => org.name)

                            return (
                                <Tooltip
                                    title={
                                        orgNames.length === 1 ? (
                                            <span>
                                                Organization <strong>{orgNames[0]}</strong> has restricted the use of
                                                personal API keys.
                                            </span>
                                        ) : (
                                            <span>
                                                Organizations <strong>{orgNames.join(', ')}</strong> have restricted the
                                                use of personal API keys.
                                            </span>
                                        )
                                    }
                                >
                                    <LemonTag type="danger">Disabled</LemonTag>
                                </Tooltip>
                            )
                        }

                        if (hasPartialRestrictions) {
                            let tooltipMessage: JSX.Element = <span />

                            // Handle project-scoped keys with restrictions
                            if (restrictedTeams.length > 0) {
                                const restrictedTeamNames = restrictedTeams.map((team: any) => team.name)
                                const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

                                if (restrictedOrgNames.length === 1 && restrictedTeamNames.length === 1) {
                                    tooltipMessage = (
                                        <span>
                                            Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use
                                            of personal API keys. This key will not work for project{' '}
                                            <strong>{restrictedTeamNames[0]}</strong>.
                                        </span>
                                    )
                                } else if (restrictedOrgNames.length === 1) {
                                    tooltipMessage = (
                                        <span>
                                            Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use
                                            of personal API keys. This key will not work for projects:{' '}
                                            <strong>{restrictedTeamNames.join(', ')}</strong>.
                                        </span>
                                    )
                                } else {
                                    // Multiple organizations affecting projects
                                    tooltipMessage = (
                                        <span>
                                            Multiple organizations have restricted personal API keys. This key will not
                                            work for projects: <strong>{restrictedTeamNames.join(', ')}</strong>.
                                        </span>
                                    )
                                }
                            }
                            // Handle organization-scoped keys with restrictions
                            else if (restrictedOrgs.length > 0) {
                                const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

                                tooltipMessage =
                                    restrictedOrgNames.length === 1 ? (
                                        <span>
                                            Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use
                                            of personal API keys.
                                        </span>
                                    ) : (
                                        <span>
                                            Organizations <strong>{restrictedOrgNames.join(', ')}</strong> have
                                            restricted the use of personal API keys.
                                        </span>
                                    )
                            }

                            return (
                                <Tooltip title={tooltipMessage}>
                                    <LemonTag type="warning">Partial restrictions</LemonTag>
                                </Tooltip>
                            )
                        }

                        return <LemonTag type="success">Active</LemonTag>
                    },
                },
                {
                    title: 'Secret key',
                    dataIndex: 'mask_value',
                    key: 'mask_value',
                    render: (_, key) =>
                        key.mask_value ? (
                            <span className="font-mono ph-no-capture">{key.mask_value}</span>
                        ) : (
                            <Tooltip title="This key was created before the introduction of previews" placement="right">
                                <span className="inline-flex items-center gap-1 cursor-default">
                                    <span>No preview</span>
                                    <IconInfo className="text-base" />
                                </span>
                            </Tooltip>
                        ),
                },
                {
                    title: 'Scopes',
                    key: 'scopes',
                    dataIndex: 'scopes',
                    render: function RenderValue(_, key) {
                        return key.scopes[0] === '*' ? (
                            <LemonTag type="warning">All access</LemonTag>
                        ) : (
                            <TagList tags={key.scopes} onMoreClick={() => setEditingKeyId(key.id)} />
                        )
                    },
                },
                {
                    title: 'Organization & project access',
                    key: 'access',
                    dataIndex: 'id',
                    render: function RenderValue(_, key) {
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

                            return (
                                <TagListWithRestrictions tags={orgTags} onMoreClick={() => setEditingKeyId(key.id)} />
                            )
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

                            return (
                                <TagListWithRestrictions tags={teamTags} onMoreClick={() => setEditingKeyId(key.id)} />
                            )
                        }
                        return <LemonTag type="warning">All access</LemonTag>
                    },
                },
                {
                    title: 'Last Used',
                    dataIndex: 'last_used_at',
                    key: 'lastUsedAt',
                    render: (_, key) => {
                        return (
                            <Tooltip title={detailedTime(key.last_used_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.last_used_at, 'MMMM DD, YYYY', 'h A')}
                            </Tooltip>
                        )
                    },
                },
                {
                    title: 'Created',
                    dataIndex: 'created_at',
                    key: 'createdAt',
                    render: (_, key) => {
                        return (
                            <Tooltip title={detailedTime(key.created_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.created_at)}
                            </Tooltip>
                        )
                    },
                },
                {
                    title: 'Last Rolled',
                    dataIndex: 'last_rolled_at',
                    key: 'lastRolledAt',
                    render: (_, key) => {
                        return (
                            <Tooltip title={detailedTime(key.last_rolled_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.last_rolled_at, 'MMMM DD, YYYY', 'h A')}
                            </Tooltip>
                        )
                    },
                },
                {
                    title: '',
                    key: 'actions',
                    align: 'right',
                    width: 0,
                    render: (_, key) => {
                        return (
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Edit',
                                        onClick: () => setEditingKeyId(key.id),
                                    },
                                    {
                                        label: 'Roll',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: `Roll key "${key.label}"?`,
                                                description:
                                                    'This will generate a new key. The old key will immediately stop working.',
                                                primaryButton: {
                                                    status: 'danger',
                                                    children: 'Roll',
                                                    type: 'primary',
                                                    onClick: () => rollKey(key.id),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                    type: 'secondary',
                                                },
                                            })
                                        },
                                    },
                                    {
                                        label: 'Delete',
                                        status: 'danger',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: `Permanently delete key "${key.label}"?`,
                                                description:
                                                    'This action cannot be undone. Make sure to have removed the key from any live integrations first.',
                                                primaryButton: {
                                                    status: 'danger',
                                                    children: 'Permanently delete',
                                                    onClick: () => deleteKey(key.id),
                                                },
                                            })
                                        },
                                    },
                                ]}
                            >
                                <LemonButton size="small" icon={<IconEllipsis />} />
                            </LemonMenu>
                        )
                    },
                },
            ]}
        />
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
