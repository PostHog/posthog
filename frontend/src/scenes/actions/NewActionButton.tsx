import { LemonModal } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconEdit, IconMagnifier } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useState } from 'react'
import { urls } from 'scenes/urls'

export function NewActionButton({ onSelectOption }: { onSelectOption?: () => void }): JSX.Element {
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
