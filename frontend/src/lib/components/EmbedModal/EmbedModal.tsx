import { LemonModal } from 'lib/components/LemonModal'
import React from 'react'
import { InsightShortId } from '~/types'

export interface ExportModalProps {
    visible: boolean
    closeModal: () => void
    insightShortId: InsightShortId
}

export function EmbedModal(props: ExportModalProps): JSX.Element {
    const { visible, closeModal } = props

    return (
        <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={650}>
            Embed stuff
        </LemonModal>
    )
}
