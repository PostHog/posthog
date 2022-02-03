import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { copyToClipboard } from 'lib/utils'
import { IconCopy, IconDeleteForever, IconLock, IconLockOpen } from 'lib/components/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature, DashboardType, UserBasicType, UserType } from '~/types'
import { FEATURE_FLAGS, DashboardRestrictionLevel, privilegeLevelToName, DashboardPrivilegeLevel } from 'lib/constants'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Select } from 'antd'
import clsx from 'clsx'

const RESTRICTION_OPTIONS: LemonSelectOptions = {
    [DashboardRestrictionLevel.EveryoneInProjectCanEdit]: {
        label: 'Everyone in the project can edit',
        icon: <IconLockOpen />,
    },
    [DashboardRestrictionLevel.OnlyCollaboratorsCanEdit]: {
        label: 'Only those invited to this dashboard can edit',
        icon: <IconLock />,
    },
}

function CollaboratorRow({
    user,
    level,
    deleteCollaborator,
}: {
    user: UserBasicType
    level: DashboardPrivilegeLevel | null
    deleteCollaborator?: (userUuid: UserType['uuid']) => void
}): JSX.Element {
    return (
        <div className={clsx('CollaboratorRow', !level && 'CollaboratorRow--owner')}>
            <ProfilePicture email={user.email} name={user.first_name} size="md" showName />
            <div className="CollaboratorRow__details">
                <span>{level ? privilegeLevelToName[level] : <b>owner</b>}</span>
                {deleteCollaborator && (
                    <LemonButton
                        icon={<IconDeleteForever />}
                        onClick={() => deleteCollaborator(user.uuid)}
                        type="stealth"
                    />
                )}
            </div>
        </div>
    )
}

export interface ShareModalProps {
    visible: boolean
    onCancel: () => void
    dashboardId: DashboardType['id']
}

export function ShareModal({ visible, onCancel, dashboardId }: ShareModalProps): JSX.Element | null {
    const { dashboardLoading } = useValues(dashboardsModel)
    const { dashboard } = useValues(dashboardLogic({ id: dashboardId }))
    const { setIsSharedDashboard, triggerDashboardUpdate } = useActions(dashboardLogic({ id: dashboardId }))
    const { explicitCollaborators, explicitCollaboratorsLoading } = useValues(
        dashboardCollaboratorsLogic({ dashboardId: dashboardId })
    )
    const { deleteExplicitCollaborator } = useActions(dashboardCollaboratorsLogic({ dashboardId: dashboardId }))
    const { hasAvailableFeature } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const shareLink = dashboard ? window.location.origin + urls.sharedDashboard(dashboard.share_token) : ''

    return dashboard ? (
        <LemonModal visible={visible} onCancel={onCancel} destroyOnClose>
            {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) &&
                featureFlags[FEATURE_FLAGS.DASHBOARD_PERMISSIONS] && (
                    <>
                        <section>
                            <h5>Dashboard restrictions</h5>
                            <LemonSelect
                                value={dashboard.restriction_level}
                                onChange={(newValue) =>
                                    triggerDashboardUpdate({
                                        restriction_level: newValue,
                                    })
                                }
                                options={RESTRICTION_OPTIONS}
                                loading={dashboardLoading}
                                type="stealth"
                                outlined
                                style={{
                                    height: '3rem',
                                    width: '100%',
                                }}
                            />
                        </section>
                        {dashboard.restriction_level > DashboardRestrictionLevel.EveryoneInProjectCanEdit && (
                            <section>
                                <h5>Collaborators</h5>
                                <Select
                                    mode="multiple"
                                    placeholder="Search for members…"
                                    loading={explicitCollaboratorsLoading}
                                    showArrow
                                    showSearch
                                    autoFocus
                                    style={{ width: '100%' }}
                                >
                                    {[].map((user: UserType) => (
                                        <Select.Option
                                            key={user.id}
                                            value={user.uuid}
                                            title={`${user.first_name} (${user.email})`}
                                        >
                                            <ProfilePicture
                                                name={user.first_name}
                                                email={user.email}
                                                size="sm"
                                                style={{ display: 'inline-flex', marginRight: 8 }}
                                            />
                                            {user.first_name} ({user.email})
                                        </Select.Option>
                                    ))}
                                </Select>
                                {dashboard.created_by && <CollaboratorRow user={dashboard.created_by} level={null} />}
                                {explicitCollaborators.map((collaborator) => (
                                    <CollaboratorRow
                                        key={collaborator.id}
                                        user={collaborator.user}
                                        level={collaborator.level}
                                        deleteCollaborator={deleteExplicitCollaborator}
                                    />
                                ))}
                            </section>
                        )}
                    </>
                )}
            <section>
                <h5>External sharing</h5>
                <LemonSwitch
                    id="share-dashboard-switch"
                    label="Share dashboard publicly"
                    checked={dashboard.is_shared}
                    loading={dashboardLoading}
                    data-attr="share-dashboard-switch"
                    onChange={(active) => {
                        setIsSharedDashboard(dashboard.id, active)
                    }}
                    type="primary"
                />
                {dashboard.is_shared ? (
                    <>
                        {dashboard.share_token && (
                            <LemonButton
                                data-attr="share-dashboard-link-button"
                                onClick={() => copyToClipboard(shareLink, 'link')}
                                icon={<IconCopy />}
                                style={{ width: '100%', height: '3rem', border: '1px solid var(--border)' }}
                            >
                                Copy shared dashboard link
                            </LemonButton>
                        )}
                        <div>Use this HTML snippet to embed the dashboard on your website:</div>
                        <CodeSnippet language={Language.HTML}>
                            {`<iframe width="100%" height="100%" frameborder="0" src="${shareLink}?embedded" />`}
                        </CodeSnippet>
                    </>
                ) : null}
            </section>
        </LemonModal>
    ) : null
}
