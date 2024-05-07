import { IconPencil, IconSearch } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
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
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                onSelectOption?.()
                                router.actions.push(urls.createAction())
                            }}
                            size="large"
                            data-attr="new-action-pageview"
                            className="flex-1"
                            center
                        >
                            <div className="p-4">
                                <IconPencil className="text-4xl mb-2" />
                                <div>From event or pageview</div>
                            </div>
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={() => setAppUrlsVisible(true)}
                            size="large"
                            data-attr="new-action-inspect"
                            className="flex-1"
                            center
                        >
                            <div className="p-4">
                                <IconSearch className="text-4xl mb-2" />
                                <div>Inspect element on your site</div>
                            </div>
                        </LemonButton>
                    </div>
                ) : (
                    <div className="max-w-200">
                        <p>
                            You can create an Action using the Toolbar running on your website. To begin select or add
                            an authorized domain and <b>launch</b> the toolbar on that site.
                        </p>
                        <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
                    </div>
                )}
            </LemonModal>
        </>
    )
}
