import React from 'react'
import { history, LOCALSTORAGE_HISTORY_KEY } from './constants'

function uniques(arr) {
    const obj = {}
    for (const a of arr) {
        obj[JSON.stringify(a)] = true
    }
    return Object.keys(obj).map((k) => JSON.parse(k))
}

export const ApiHistory = ({ saveApi }) => {
    const localHistory = JSON.parse(window.localStorage.getItem(LOCALSTORAGE_HISTORY_KEY) || '[]')
    const allOfHistory = uniques([...localHistory, ...history])

    return (
        <div style={{ margin: 10 }}>
            <strong style={{ display: 'block', marginBottom: 5 }}>History</strong>
            {allOfHistory.map(({ apiHost, apiKey }) => (
                <button
                    onClick={() => saveApi(apiHost, apiKey)}
                    style={{
                        display: 'block',
                        width: '100%',
                        marginBottom: 3,
                        textAlign: 'left',
                        cursor: 'pointer',
                    }}
                >
                    <small style={{ opacity: 0.8 }}>Host:</small> {apiHost || ''}
                    <br />
                    <small style={{ opacity: 0.8 }}>Key:</small> {apiKey ? `${apiKey.substring(0, 10)}...` : ''}
                </button>
            ))}
        </div>
    )
}
