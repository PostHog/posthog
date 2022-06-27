import React from 'react'
import { LemonModal } from 'lib/components/LemonModal'
import { SharingBaseProps } from './utils'
import { InsightShortId } from '~/types'

export interface SharingModalProps extends SharingBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    visible: boolean
    closeModal: () => void
}

export function Sharing(props: SharingModalProps): JSX.Element {
    const { closeModal, dashboardId, insightShortId } = props

    return (
        <>
            <p>Hello!</p>
        </>
    )
}

export function SharingModal(props: SharingModalProps): JSX.Element {
    const { visible, closeModal } = props

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible}>
                <Sharing {...props} />
            </LemonModal>
        </>
    )
}
