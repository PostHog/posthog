import React from 'react'
import { ActionAttribute } from '~/toolbar/shared/ActionAttribute'

export function ActionStep({ actionStep }) {
    return (
        <div>
            <div style={{ fontSize: 16, marginBottom: 10 }}>&lt;{actionStep.tag_name}&gt;</div>
            {['text', 'name', 'href', 'selector'].map(attr =>
                actionStep[attr] ? <ActionAttribute key={attr} attribute={attr} value={actionStep[attr]} /> : null
            )}
        </div>
    )
}
