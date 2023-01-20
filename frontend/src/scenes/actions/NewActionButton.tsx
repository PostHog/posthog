import { useState } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconEdit, IconMagnifier } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from '@posthog/lemon-ui'

export function NewActionButton(): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [appUrlsVisible, setAppUrlsVisible] = useState(false)

    return (
        <>
            <LemonButton type="primary" onClick={() => setVisible(true)} data-attr="create-action">
                New action
            </LemonButton>
            <LemonModal
                isOpen={visible}
                onClose={() => {
                    setVisible(false)
                    setAppUrlsVisible(false)
                }}
                title={`Create new action`}
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
                            data-attr="new-action-inspect"
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
                            data-attr="new-action-pageview"
                        >
                            From event or pageview
                        </LemonButton>
                    </div>
                ) : (
                    <div style={{ maxWidth: '40rem' }}>
                        <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
                    </div>
                )}
            </LemonModal>
        </>
    )
}
