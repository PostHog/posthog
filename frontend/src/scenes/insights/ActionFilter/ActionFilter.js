import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PlusCircleOutlined } from '@ant-design/icons'

export function ActionFilter({ setFilters, filters, typeKey, hideMathSelector, copy = '' }) {
    const logic = entityFilterLogic({ setFilters, filters, typeKey })

    const { localFilters } = useValues(logic)
    const { addFilter, setLocalFilters } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
    // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
    useEffect(() => {
        setLocalFilters(filters)
    }, [filters])

    return (
        <div>
            {localFilters &&
                localFilters.map((filter, index) => (
                    <ActionFilterRow
                        logic={logic}
                        filter={filter}
                        index={index}
                        key={index}
                        hideMathSelector={hideMathSelector}
                    />
                ))}
            <div style={!featureFlags['actions-ux-201012'] ? {} : { paddingTop: '0.5rem' }}>
                <Button
                    type="primary"
                    onClick={() => addFilter()}
                    style={{ marginTop: '0.5rem' }}
                    data-attr="add-action-event-button"
                    icon={featureFlags['actions-ux-201012'] && <PlusCircleOutlined />}
                >
                    {!featureFlags['actions-ux-201012'] ? 'Add action/event' : copy || 'Action or raw event'}
                </Button>
            </div>
        </div>
    )
}
