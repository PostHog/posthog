import React from 'react'

export function SelectorCount({ selector }) {
    let selectorError = false
    let matches

    if (selector) {
        try {
            matches = document.querySelectorAll(selector).length
        } catch {
            selectorError = true
        }
    }
    return (
        <small style={{ float: 'right', color: selectorError ? 'red' : '' }}>
            {selectorError ? 'Invalid selector' : `Matches ${matches} element${matches === 1 ? '' : 's'}`}
        </small>
    )
}
