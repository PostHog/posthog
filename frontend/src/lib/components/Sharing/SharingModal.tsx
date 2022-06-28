import React from 'react'
import { LemonModal } from 'lib/components/LemonModal'
import { SharingBaseProps } from './utils'
import { InsightShortId } from '~/types'
import { useActions, useValues } from 'kea'
import { sharingLogic } from './sharingLogic'
import { Skeleton } from 'antd'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { copyToClipboard } from 'lib/utils'
import { urls } from 'scenes/urls'
import { IconCopy } from '../icons'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

export interface SharingModalProps extends SharingBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    visible: boolean
    closeModal: () => void
}

export function Sharing(props: SharingModalProps): JSX.Element {
    const { dashboardId, insightShortId } = props

    const logic = sharingLogic({
        dashboardId,
        insightShortId,
    })

    const { sharingConfiguration, sharingConfigurationLoading } = useValues(logic)
    const { setIsEnabled } = useActions(logic)

    const resource = dashboardId ? 'dashboard' : 'insight'

    const shareLink = sharingConfiguration
        ? window.location.origin + urls.shared(sharingConfiguration.access_token)
        : ''

    return (
        <>
            <header className="border-bottom pb-05">
                <h4 className="mt-05">Share or embed {resource}</h4>
            </header>

            <section>
                {!sharingConfiguration && sharingConfigurationLoading ? (
                    <Skeleton />
                ) : !sharingConfiguration ? (
                    <p>Something went wrong...</p>
                ) : (
                    <div className="space-y-05">
                        <LemonSwitch
                            id="sharing-switch"
                            label={`Share ${resource} publicly`}
                            checked={sharingConfiguration.enabled}
                            loading={sharingConfigurationLoading}
                            data-attr="sharing-switch"
                            onChange={(active) => {
                                console.log('CHANGED', active)
                                setIsEnabled(active)
                                // setIsSharedDashboard(dashboard.id, active)
                            }}
                            type="primary"
                            style={{ width: '100%', height: '3rem', fontWeight: 600 }}
                        />

                        {sharingConfiguration.enabled ? (
                            <>
                                {sharingConfiguration.access_token && (
                                    <LemonButton
                                        data-attr="sharing-link-button"
                                        type="secondary"
                                        onClick={() => copyToClipboard(shareLink, 'link')}
                                        icon={<IconCopy />}
                                        fullWidth
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
                    </div>
                )}
            </section>
        </>
    )
}

export function SharingModal(props: SharingModalProps): JSX.Element {
    const { visible, closeModal } = props

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible}>
                <Sharing {...props} />
            </LemonModal>
        </>
    )
}
