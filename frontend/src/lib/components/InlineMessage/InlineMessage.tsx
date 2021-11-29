import React, { useState } from 'react'
import './InlineMessage.scss'
import { ExclamationCircleFilled, CloseOutlined } from '@ant-design/icons'
import clsx from 'clsx'

interface InlineMessageProps {
    children: string | JSX.Element
    style?: React.CSSProperties
    icon?: JSX.Element
    type?: 'danger' | 'warning' | 'info'
    closable?: boolean
    onClose?: () => void
}

// New UI for inline inline messages (e.g. info/warning/error)
export function InlineMessage({
    children,
    style,
    icon = <ExclamationCircleFilled />,
    type = 'info',
    closable,
    onClose,
}: InlineMessageProps): JSX.Element {
    const [shown, setShown] = useState(true)

    const handleClose = (): void => {
        setShown(false)
        onClose?.()
    }

    return (
        <div className={clsx('inline-message', type, closable && 'closable', !shown && 'hidden')} style={style}>
            <div className="inline-icon">{icon}</div>
            <div className="inline-main">{children}</div>
            {closable && (
                <div className="closable" onClick={handleClose}>
                    <CloseOutlined />
                </div>
            )}
        </div>
    )
}
