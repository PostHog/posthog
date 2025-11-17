import { router } from 'kea-router'
import { useState } from 'react'

import { IconPencil, IconSearch } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function NewActionButton({ onSelectOption }: { onSelectOption?: () => void }): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [appUrlsVisible, setAppUrlsVisible] = useState(false)

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Action}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton size="small" type="primary" onClick={() => setVisible(true)} data-attr="create-action">
                    New action
                </LemonButton>
            </AccessControlAction>
            <LemonModal
                isOpen={visible}
                onClose={() => {
                    setVisible(false)
                    setAppUrlsVisible(false)
                }}
                title="Create new action"
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
                    <div className="deprecated-space-y-2">
                        <LemonButton
                            type="secondary"
                            icon={<IconSearch />}
                            onClick={() => setAppUrlsVisible(true)}
                            size="large"
                            fullWidth
                            center
                            data-attr="new-action-inspect"
                        >
                            Inspect element on your site
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={() => {
                                onSelectOption?.()
                                router.actions.push(urls.createAction())
                            }}
                            size="large"
                            fullWidth
                            center
                            data-attr="new-action-pageview"
                        >
                            From event or pageview
                        </LemonButton>
                    </div>
                ) : (
                    <div className="max-w-160">
                        <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
                    </div>
                )}
            </LemonModal>
        </>
    )
}
