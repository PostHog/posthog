import React from 'react'
import { Actions } from '~/editor/Actions'
import { SearchOutlined } from '@ant-design/icons'
import { CurrentPage } from '~/editor/CurrentPage'

export function Toolbar({ apiURL, temporaryToken, actionId }) {
    return (
        <div>
            <CurrentPage />
            <div className="float-box button">
                <p>
                    <SearchOutlined /> Inspect an element
                </p>
                <small>Use the inspector select an element on the page and see associated analytics here</small>
            </div>
            <div className="float-box">
                <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
            </div>
        </div>
    )
}
