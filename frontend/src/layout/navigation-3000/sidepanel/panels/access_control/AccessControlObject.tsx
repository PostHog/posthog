import { IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonSelectProps,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useAsyncActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UserSelectItem } from 'lib/components/UserSelectItem'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfileBubbles, ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    AccessControlType,
    AccessControlTypeMember,
    AccessControlTypeRole,
    AvailableFeature,
    OrganizationMemberType,
} from '~/types'

import { accessControlLogic, AccessControlLogicProps } from './accessControlLogic'

export function AccessControlObject(props: AccessControlLogicProps): JSX.Element | null {
    const { canEditAccessControls, humanReadableResource } = useValues(accessControlLogic(props))

    const suffix = `this ${humanReadableResource}`

    return (
        <BindLogic logic={accessControlLogic} props={props}>
            <div className="deprecated-space-y-6">
                {canEditAccessControls === false ? (
                    <LemonBanner type="warning">
                        <b>Permission required</b>
                        <br />
                        You don't have permission to edit access controls for {suffix}. You must be the{' '}
                        <i>creator of it</i>, a <i>Project admin</i>, or an <i>Organization admin</i>.
                    </LemonBanner>
                ) : null}

                <div className="deprecated-space-y-2">
                    <h3>Default access to {suffix}</h3>
                    <AccessControlObjectDefaults />
                </div>

                <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS} className="deprecated-space-y-6">
                    <AccessControlObjectUsers />

                    {/* Put this inside of Advanced Permissions so two aren't shown at once */}
                    <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                        <AccessControlObjectRoles />
                    </PayGateMini>
                </PayGateMini>
            </div>
        </BindLogic>
    )
}

function AccessControlObjectDefaults(): JSX.Element | null {
    const { accessControlDefault, accessControlDefaultOptions, accessControlsLoading, canEditAccessControls } =
        useValues(accessControlLogic)
    const { updateAccessControlDefault } = useActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    return (
        <LemonSelect
            placeholder="Loading..."
            value={accessControlDefault?.access_level ?? undefined}
            onChange={(newValue) => {
                guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS, () => {
                    updateAccessControlDefault(newValue)
                })
            }}
            disabledReason={
                accessControlsLoading ? 'Loading…' : !canEditAccessControls ? 'You cannot edit this' : undefined
            }
            dropdownMatchSelectWidth={false}
            options={accessControlDefaultOptions}
        />
    )
}

function AccessControlObjectUsers(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const {
        membersById,
        addableMembers,
        accessControlMembers,
        accessControlsLoading,
        availableLevels,
        canEditAccessControls,
    } = useValues(accessControlLogic)
    const { updateAccessControlMembers } = useAsyncActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const [modelOpen, setModelOpen] = useState(false)

    if (!user) {
        return null
    }

    const member = (ac: AccessControlTypeMember): OrganizationMemberType => {
        return membersById[ac.organization_member]
    }

    // TODO: WHAT A MESS - Fix this to do the index mapping beforehand...
    const columns: LemonTableColumns<AccessControlTypeMember> = [
        {
            key: 'user',
            title: 'User',
            render: (_, ac) => (
                <div className="flex items-center gap-2">
                    <ProfilePicture user={member(ac)?.user} />
                    <div>
                        <p className="font-medium mb-0">
                            {member(ac)?.user.uuid == user.uuid
                                ? `${member(ac)?.user.first_name} (you)`
                                : member(ac)?.user.first_name}
                        </p>
                        <p className="text-secondary mb-0">{member(ac)?.user.email}</p>
                    </div>
                </div>
            ),
            sorter: (a, b) => member(a)?.user.first_name.localeCompare(member(b)?.user.first_name),
        },
        {
            key: 'level',
            title: 'Level',
            width: 0,
            render: function LevelRender(_, { access_level, organization_member, resource }) {
                return resource === 'organization' ? (
                    <Tooltip title="Organization owners and admins have access to all resources in the organization">
                        <LemonTag type="muted">Organization admin</LemonTag>
                    </Tooltip>
                ) : (
                    <div className="my-1">
                        <SimplLevelComponent
                            size="small"
                            level={access_level}
                            levels={availableLevels}
                            onChange={(level) =>
                                void updateAccessControlMembers([{ member: organization_member, level }])
                            }
                        />
                    </div>
                )
            },
        },
        {
            key: 'remove',
            width: 0,
            render: (_, { organization_member, resource }) => {
                return resource === 'organization' ? null : (
                    <RemoveAccessButton
                        subject="member"
                        onConfirm={() =>
                            void updateAccessControlMembers([{ member: organization_member, level: null }])
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <div className="deprecated-space-y-2">
                <div className="flex gap-2 items-center justify-between">
                    <h3 className="mb-0">Members</h3>
                    <LemonButton
                        type="primary"
                        onClick={() => setModelOpen(true)}
                        disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
                    >
                        Add
                    </LemonButton>
                </div>

                <LemonTable columns={columns} dataSource={accessControlMembers} loading={accessControlsLoading} />
            </div>

            <AddItemsControlsModal
                modelOpen={modelOpen}
                setModelOpen={setModelOpen}
                placeholder="Search for team members to add…"
                onAdd={async (newValues, level) => {
                    if (guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS)) {
                        await updateAccessControlMembers(newValues.map((member) => ({ member, level })))
                        setModelOpen(false)
                    }
                }}
                options={addableMembers.map((member) => ({
                    key: member.id,
                    label: `${member.user.first_name} ${member.user.email}`,
                    labelComponent: <UserSelectItem user={member.user} />,
                }))}
            />
        </>
    )
}

function AccessControlObjectRoles(): JSX.Element | null {
    const {
        accessControlRoles,
        accessControlsLoading,
        addableRoles,
        rolesById,
        availableLevels,
        canEditAccessControls,
    } = useValues(accessControlLogic)
    const { updateAccessControlRoles } = useAsyncActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const [modelOpen, setModelOpen] = useState(false)

    const columns: LemonTableColumns<AccessControlTypeRole> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, { role }) => (
                <span className="whitespace-nowrap">
                    <LemonTableLink
                        to={urls.settings('organization-roles') + `#role=${role}`}
                        title={rolesById[role]?.name}
                    />
                </span>
            ),
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, { role }) => {
                return (
                    <ProfileBubbles
                        people={
                            rolesById[role]?.members?.map((member) => ({
                                email: member.user.email,
                                name: member.user.first_name,
                                title: `${member.user.first_name} <${member.user.email}>`,
                            })) ?? []
                        }
                    />
                )
            },
        },
        {
            title: 'Level',
            key: 'level',
            width: 0,
            render: (_, { access_level, role }) => {
                return (
                    <div className="my-1">
                        <SimplLevelComponent
                            size="small"
                            level={access_level}
                            levels={availableLevels}
                            onChange={(level) => void updateAccessControlRoles([{ role, level }])}
                        />
                    </div>
                )
            },
        },
        {
            key: 'remove',
            width: 0,
            render: (_, { role }) => {
                return (
                    <RemoveAccessButton
                        subject="role"
                        onConfirm={() => void updateAccessControlRoles([{ role, level: null }])}
                    />
                )
            },
        },
    ]

    return (
        <>
            <div className="deprecated-space-y-2">
                <div className="flex gap-2 items-center justify-between">
                    <h3 className="mb-0">Roles</h3>
                    <LemonButton
                        type="primary"
                        onClick={() => setModelOpen(true)}
                        disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
                    >
                        Add
                    </LemonButton>
                </div>

                <LemonTable columns={columns} dataSource={accessControlRoles} loading={accessControlsLoading} />
            </div>

            <AddItemsControlsModal
                modelOpen={modelOpen}
                setModelOpen={setModelOpen}
                placeholder="Search for roles to add…"
                onAdd={async (newValues, level) => {
                    if (guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS)) {
                        await updateAccessControlRoles(newValues.map((role) => ({ role, level })))
                        setModelOpen(false)
                    }
                }}
                options={addableRoles.map((role) => ({
                    key: role.id,
                    label: role.name,
                }))}
            />
        </>
    )
}

function SimplLevelComponent(props: {
    size?: LemonSelectProps<any>['size']
    level: AccessControlType['access_level'] | null
    levels: AccessControlType['access_level'][]
    onChange: (newValue: AccessControlType['access_level']) => void
}): JSX.Element | null {
    const { canEditAccessControls } = useValues(accessControlLogic)

    return (
        <LemonSelect
            size={props.size}
            placeholder="Select level..."
            value={props.level}
            onChange={(newValue) => props.onChange(newValue)}
            disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
            options={props.levels.map((level) => ({
                value: level,
                label: capitalizeFirstLetter(level ?? ''),
            }))}
        />
    )
}

function RemoveAccessButton({
    onConfirm,
    subject,
}: {
    onConfirm: () => void
    subject: 'member' | 'role'
}): JSX.Element {
    const { canEditAccessControls } = useValues(accessControlLogic)

    return (
        <LemonButton
            icon={<IconTrash />}
            size="small"
            disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
            onClick={() =>
                LemonDialog.open({
                    title: 'Remove access',
                    content: `Are you sure you want to remove this ${subject}'s explicit access?`,
                    primaryButton: {
                        children: 'Remove',
                        status: 'danger',
                        onClick: () => onConfirm(),
                    },
                })
            }
        />
    )
}

function AddItemsControlsModal(props: {
    modelOpen: boolean
    setModelOpen: (open: boolean) => void
    placeholder: string
    onAdd: (newValues: string[], level: AccessControlType['access_level']) => Promise<void>
    options: {
        key: string
        label: string
    }[]
}): JSX.Element | null {
    const { availableLevels, canEditAccessControls } = useValues(accessControlLogic)
    // TODO: Move this into a form logic
    const [items, setItems] = useState<string[]>([])
    const [level, setLevel] = useState<AccessControlType['access_level']>(availableLevels[0] ?? null)

    useEffect(() => {
        setLevel(availableLevels[0] ?? null)
    }, [availableLevels])

    const onSubmit =
        items.length && level
            ? (): void =>
                  void props.onAdd(items, level).then(() => {
                      setItems([])
                      setLevel(availableLevels[0] ?? null)
                  })
            : undefined

    return (
        <LemonModal
            isOpen={props.modelOpen || false}
            onClose={() => props.setModelOpen(false)}
            title="Add access"
            maxWidth="30rem"
            description="Allow other users or roles to access this resource"
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={() => props.setModelOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        disabledReason={
                            !canEditAccessControls
                                ? 'You cannot edit this'
                                : !onSubmit
                                ? 'Please choose what you want to add and at what level'
                                : undefined
                        }
                    >
                        Add
                    </LemonButton>
                </div>
            }
        >
            <div className="flex gap-2 items-center w-full">
                <div className="min-w-[16rem] w-full">
                    <LemonInputSelect
                        placeholder={props.placeholder}
                        value={items}
                        onChange={(newValues: string[]) => setItems(newValues)}
                        mode="multiple"
                        options={props.options}
                        disabled={!canEditAccessControls}
                    />
                </div>
                <SimplLevelComponent levels={availableLevels} level={level} onChange={setLevel} />
            </div>
        </LemonModal>
    )
}
