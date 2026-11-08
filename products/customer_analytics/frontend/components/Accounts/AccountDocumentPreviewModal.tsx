import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { accountDocumentsLogic, AccountDocumentsLogicProps } from './accountDocumentsLogic'

export function AccountDocumentPreviewModal({ accountId, instanceId }: AccountDocumentsLogicProps): JSX.Element {
    const logic = accountDocumentsLogic({ accountId, instanceId })
    const { previewDocument, previewUrl } = useValues(logic)
    const { closePreview, reportDocumentOpened } = useActions(logic)

    return (
        <LemonModal
            isOpen={!!previewDocument}
            onClose={closePreview}
            title={previewDocument?.title || 'Document preview'}
            description="The current version from PandaDoc, including unsigned drafts."
            width={960}
            footer={
                <>
                    {previewDocument?.pandadoc_url && (
                        <LemonButton
                            type="secondary"
                            to={previewDocument.pandadoc_url}
                            targetBlank
                            onClick={() => reportDocumentOpened(previewDocument, 'pandadoc')}
                            data-attr="account-document-open-pandadoc"
                        >
                            Open in PandaDoc
                        </LemonButton>
                    )}
                    <LemonButton type="primary" onClick={closePreview}>
                        Close
                    </LemonButton>
                </>
            }
        >
            {previewDocument && (
                // The frame follows the viewport because a fixed pixel height cuts a PDF page in half on short screens.
                <iframe
                    title={previewDocument.title}
                    src={previewUrl(previewDocument)}
                    className="w-full h-[70vh] border rounded bg-surface-primary"
                    data-attr="account-document-preview-frame"
                />
            )}
        </LemonModal>
    )
}
