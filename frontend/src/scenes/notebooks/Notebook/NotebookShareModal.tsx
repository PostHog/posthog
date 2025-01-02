import { IconCopy, IconOpenSidebar } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { SHARING_MODAL_WIDTH } from 'lib/components/Sharing/SharingModal'
import { base64Encode } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import posthog from 'posthog-js'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { notebookLogic } from './notebookLogic'

export type NotebookShareModalProps = {
    shortId: string
}

export function NotebookShareModal({ shortId }: NotebookShareModalProps): JSX.Element {
    const { content, isLocalOnly, isShareModalOpen } = useValues(notebookLogic({ shortId }))
    const { closeShareModal } = useActions(notebookLogic({ shortId }))
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const notebookUrl = urls.absolute(urls.currentProject(urls.notebook(shortId)))
    const canvasUrl = urls.absolute(urls.canvas()) + `#🦔=${base64Encode(JSON.stringify(content))}`

    const [interestTracked, setInterestTracked] = useState(false)

    const trackInterest = (): void => {
        posthog.capture('pressed interested in notebook sharing', { url: notebookUrl })
    }

    return (
        <LemonModal
            title="Share notebook"
            onClose={() => closeShareModal()}
            isOpen={isShareModalOpen}
            width={SHARING_MODAL_WIDTH}
            footer={
                <LemonButton type="secondary" onClick={closeShareModal}>
                    Done
                </LemonButton>
            }
        >
            <div className="space-y-4">
                <FlaggedFeature flag="role-based-access-control">
                    <>
                        <div>
                            <h3>Access control</h3>
                            <LemonBanner type="info" className="mb-4">
                                Permissions have moved! We're rolling out our new access control system. Click below to
                                open it.
                            </LemonBanner>
                            <LemonButton
                                type="primary"
                                icon={<IconOpenSidebar />}
                                onClick={() => {
                                    openSidePanel(SidePanelTab.AccessControl)
                                    closeShareModal()
                                }}
                            >
                                Open access control
                            </LemonButton>
                        </div>
                        <LemonDivider />
                    </>
                </FlaggedFeature>
                <h3>Internal Link</h3>
                {!isLocalOnly ? (
                    <>
                        <p>
                            <b>Click the button below</b> to copy a direct link to this Notebook. Make sure the person
                            you share it with has access to this PostHog project.
                        </p>
                        <LemonButton
                            type="secondary"
                            fullWidth
                            center
                            sideIcon={<IconCopy />}
                            onClick={() => void copyToClipboard(notebookUrl, 'notebook link')}
                            title={notebookUrl}
                        >
                            <span className="truncate">{notebookUrl}</span>
                        </LemonButton>

                        <LemonDivider className="my-4" />
                    </>
                ) : (
                    <LemonBanner type="info">
                        <p>This Notebook cannot be shared directly with others as it is only visible to you.</p>
                    </LemonBanner>
                )}

                <h3>Template Link</h3>
                <p>
                    The link below will open a Canvas with the contents of this Notebook, allowing the receiver to view
                    it, edit it or create their own Notebook without affecting this one.
                </p>
                <LemonButton
                    type="secondary"
                    fullWidth
                    center
                    sideIcon={<IconCopy />}
                    onClick={() => void copyToClipboard(canvasUrl, 'canvas link')}
                    title={canvasUrl}
                >
                    <span className="truncate">{canvasUrl}</span>
                </LemonButton>

                <LemonDivider className="my-4" />

                <h3>External Sharing</h3>

                <LemonBanner
                    type="warning"
                    action={{
                        children: !interestTracked ? 'I would like this!' : 'Thanks!',
                        onClick: () => {
                            if (!interestTracked) {
                                trackInterest()
                                setInterestTracked(true)
                            }
                        },
                    }}
                >
                    We don’t currently support sharing notebooks externally, but it’s on our roadmap!
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
