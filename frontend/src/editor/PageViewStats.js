import React from 'react'

export function PageViewStats() {
    return (
        <div className="float-box">
            <div>
                <span style={{ borderBottom: '2px dashed hsla(230, 14%, 78%, 1)' }}>Last 24 hours</span>
            </div>
            <p>
                <span>1234</span> pageviews
            </p>
            <p>
                <span>534</span> unique visitors
            </p>
        </div>
    )
}
