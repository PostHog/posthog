import React from 'react'
import ReactMarkdown from 'react-markdown'
import clsx from 'clsx'
import { CloseOutlined } from '@ant-design/icons'

export interface AnnouncementProps {
    message: string
    visible: boolean
    onClose: () => void
}

export function Announcement({ message, visible, onClose }: AnnouncementProps): JSX.Element {
    return (
        <div className={clsx('Announcement', !visible && 'Announcement--hidden')}>
            <ReactMarkdown>{message}</ReactMarkdown>
            <CloseOutlined className="Announcement__close" onClick={onClose} />
        </div>
    )
}
