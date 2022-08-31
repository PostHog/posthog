import React, { useState } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { AuthorizedUrls } from 'scenes/toolbar-launch/AuthorizedUrls'
import { IconEdit, IconMagnifier } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonModal } from '@posthog/lemon-ui'

export function NewActionButton(): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [appUrlsVisible, setAppUrlsVisible] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <LemonButton type="primary" onClick={() => setVisible(true)} data-attr="create-action">
                New {featureFlags[FEATURE_FLAGS.SIMPLIFY_ACTIONS] ? 'calculated event' : 'action'}
            </LemonButton>
            <LemonModal
                isOpen={visible}
                onClose={() => {
                    setVisible(false)
                    setAppUrlsVisible(false)
                }}
                title={`Create new ${featureFlags[FEATURE_FLAGS.SIMPLIFY_ACTIONS] ? 'calculated event' : 'action'}`}
                footer={
                    <>
                        {appUrlsVisible && (
                            <LemonButton key="back-button" type="secondary" onClick={() => setAppUrlsVisible(false)}>
                                Back
                            </LemonButton>
                        )}
                        <LemonButton
                            key="cancel-button"
                            type="secondary"
                            onClick={() => {
                                setVisible(false)
                                setAppUrlsVisible(false)
                            }}
                        >
                            Cancel
                        </LemonButton>
                    </>
                }
            >
                {!appUrlsVisible ? (
                    <div className="space-y-2">
                        <LemonButton
                            type="secondary"
                            icon={<IconMagnifier />}
                            onClick={() => setAppUrlsVisible(true)}
                            size="large"
                            fullWidth
                            center
                        >
                            Inspect element on your site
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            icon={<IconEdit />}
                            onClick={() => {
                                router.actions.push(urls.createAction())
                            }}
                            size="large"
                            fullWidth
                            center
                        >
                            From event or pageview
                        </LemonButton>
                    </div>
                ) : (
                    <AuthorizedUrls />
                )}
            </LemonModal>
        </>
    )
}
