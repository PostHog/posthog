import React from 'react'
import { Modal, ModalProps } from 'antd'
import { IconClose } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import clsx from 'clsx'
import './LemonModal.scss'

/** A lightweight wrapper over Ant's Modal for matching Lemon style. */
export function LemonModal({
    className,
    footer = null,
    width = 480,
    ...modalProps
}: React.PropsWithChildren<ModalProps>): JSX.Element {
    return (
        <Modal
            {...modalProps}
            footer={footer}
            width={width}
            closeIcon={<LemonButton icon={<IconClose />} type="stealth" />}
            className={clsx('LemonModal', className)}
        />
    )
}
