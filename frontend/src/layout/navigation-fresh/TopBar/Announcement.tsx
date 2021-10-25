import React from 'react'
import ReactMarkdown from 'react-markdown'

export interface AnnouncementProps {
    message: string
}

export function Announcement({ message }: AnnouncementProps): JSX.Element {
    return (
        <div className="TopBar__announcement">
            <ReactMarkdown>{message}</ReactMarkdown>
        </div>
    )
}
