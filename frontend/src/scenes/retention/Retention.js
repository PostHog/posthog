import React from 'react'
import { hot } from 'react-hot-loader/root'

import { RetentionTable } from './RetentionTable'
import { retentionTableLogic } from './retentionTableLogic'

export const Retention = hot(_Retention)
function _Retention() {
    return (
        <div>
            <h1 className="page-header">Retention</h1>

            <RetentionTable logic={retentionTableLogic} />
        </div>
    )
}
