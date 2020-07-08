import React from 'react'
import { ActionAttribute } from '~/toolbar/elements/ActionAttribute'

export function ActionStep({ actionStep }) {
    return (
        <div>
            {['text', 'name', 'href', 'selector'].map((attr) =>
                actionStep[attr] ? <ActionAttribute key={attr} attribute={attr} value={actionStep[attr]} /> : null
            )}
        </div>
    )
}
