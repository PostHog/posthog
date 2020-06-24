import React from 'react'
import { hot } from 'react-hot-loader/root'

import { RetentionTable } from './RetentionTable'
import { retentionTableLogic } from './retentionTableLogic'

export const Retention = hot(_Retention)
function _Retention() {
    return (
        <div>
            <h1 className="page-header">Retention</h1>
            <p style={{ maxWidth: 600 }}>
                <i>Retention table shows how many users return on subsequent days after visiting the site.</i>
            </p>

            <RetentionTable logic={retentionTableLogic} />
        </div>
    )
}
