import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'

import { SHARING_MODAL_WIDTH } from 'lib/components/Sharing/SharingModal'
import { base64Encode } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { AccessControlPopoutCTA } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlPopoutCTA'
import { AccessControlResourceType } from '~/types'

import { notebookLogic } from './notebookLogic'

export type NotebookShareModalProps = {
    shortId: string
}

export function NotebookShareModal({ shortId }: NotebookShareModalProps): JSX.Element {
    const { content, isLocalOnly, isShareModalOpen } = useValues(notebookLogic({ shortId }))
    const { closeShareModal } = useActions(notebookLogic({ shortId }))

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
            <div className="deprecated-space-y-4">
                <AccessControlPopoutCTA
                    resourceType={AccessControlResourceType.Notebook}
                    callback={() => {
                        closeShareModal()
                    }}
                />
                <LemonDivider />
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
