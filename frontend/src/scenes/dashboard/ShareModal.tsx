import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { copyToClipboard } from 'lib/utils'
import { IconCopy } from 'lib/components/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature, DashboardRestrictionLevel } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSpacer } from 'lib/components/LemonRow'

export function ShareModal({ visible, onCancel }: { visible: boolean; onCancel: () => void }): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)
    const { dashboardLoading } = useValues(dashboardsModel)
    const { setIsSharedDashboard, triggerDashboardUpdate } = useActions(dashboardLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const shareLink = dashboard ? window.location.origin + urls.sharedDashboard(dashboard.share_token) : ''

    return dashboard ? (
        <LemonModal visible={visible} onCancel={onCancel} destroyOnClose>
            {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) &&
                featureFlags[FEATURE_FLAGS.DASHBOARD_PERMISSIONS] && (
                    <>
                        <h5>Dashboard collaboration</h5>
                        <LemonButtonWithPopup
                            fullWidth
                            type="stealth"
                            popup={{
                                overlay: (
                                    <>
                                        <LemonButton
                                            fullWidth
                                            type={
                                                dashboard.restriction_level ===
                                                DashboardRestrictionLevel.EveryoneInProjectCanEdit
                                                    ? 'highlighted'
                                                    : 'stealth'
                                            }
                                            onClick={() =>
                                                triggerDashboardUpdate({
                                                    restriction_level:
                                                        DashboardRestrictionLevel.EveryoneInProjectCanEdit,
                                                })
                                            }
                                        >
                                            Everyone in the project can view
                                        </LemonButton>
                                        <LemonButton
                                            fullWidth
                                            type={
                                                dashboard.restriction_level ===
                                                DashboardRestrictionLevel.OnlyCollaboratorsCanEdit
                                                    ? 'highlighted'
                                                    : 'stealth'
                                            }
                                            onClick={() =>
                                                triggerDashboardUpdate({
                                                    restriction_level:
                                                        DashboardRestrictionLevel.OnlyCollaboratorsCanEdit,
                                                })
                                            }
                                        >
                                            Only those invited to this dashboard can edit
                                        </LemonButton>
                                    </>
                                ),
                                actionable: true,
                                sameWidth: true,
                            }}
                            style={{
                                height: '3rem',
                                border: '1px solid var(--border)',
                            }}
                        >
                            {dashboard.restriction_level === DashboardRestrictionLevel.OnlyCollaboratorsCanEdit
                                ? 'Only those invited to this dashboard can edit'
                                : 'Everyone in the project can view'}
                        </LemonButtonWithPopup>
                        <LemonSpacer />
                    </>
                )}
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
                outlinedBlock
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
        </LemonModal>
    ) : null
}
