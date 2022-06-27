import { LemonModal } from 'lib/components/LemonModal'
import React from 'react'
import { InsightShortId } from '~/types'
import { urls } from 'scenes/urls'

export interface ExportModalProps {
    visible: boolean
    closeModal: () => void
    insightShortId: InsightShortId
}

export function EmbedModal({ visible, closeModal, insightShortId }: ExportModalProps): JSX.Element {
    return (
        <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={650}>
            Embed stuff
            <iframe style={{ width: '100%', height: 300 }} src={urls.exportPreview({ insight: insightShortId })} />
        </LemonModal>
    )
}
