import React from 'react'
import './ActionComponents.scss'
import { capitalizeFirstLetter } from '~/lib/utils'
import { AimOutlined, ContainerOutlined } from '@ant-design/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'

export function ActionSelectTab({ entityType, chooseEntityType, allTypes }) {
    const { featureFlags } = useValues(featureFlagLogic)
    const icon = (type) => {
        // TODO: Move to kea logic
        if (type === 'actions') {
            return <AimOutlined style={{ paddingRight: 6 }} />
        } else if (type === 'events') {
            return <ContainerOutlined style={{ paddingRight: 6 }} />
        }
    }
    return (
        <div className={'ast-container ' + (featureFlags['actions-ux-201012'] ? 'ast-v2' : '')}>
            {allTypes.map((type, index) => (
                <div
                    className={'ast-tab ' + (entityType == type ? 'active' : '')}
                    key={index}
                    onClick={() => chooseEntityType(type)}
                >
                    {featureFlags['actions-ux-201012'] && icon(type)}
                    {capitalizeFirstLetter(type.replace('_', ' '))}
                </div>
            ))}
        </div>
    )
}
