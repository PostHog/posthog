import React from 'react'
import { CohortNameInput } from './CohortNameInput'
import { CohortDescriptionInput } from './CohortDescriptionInput'
import { CohortTypeSelector } from './CohortTypeSelector'
import { Divider } from 'antd'
import { CohortMatchingCriteriaSection } from './CohortMatchingCriteriaSection'

export function CohortV2(): JSX.Element {
    const onChangeName = (): void => {}

    const onChangeDescription = (): void => {}

    return (
        <div style={{ maxWidth: 1200 }} className="mb">
            <div style={{ display: 'flex', flexDirection: 'row' }}>
                <div style={{ flex: 6 }}>
                    <CohortNameInput onChange={onChangeName} />
                </div>
                <div style={{ flex: 4, marginLeft: 20 }}>
                    <CohortTypeSelector />
                </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'row' }}>
                <div style={{ flex: 6 }}>
                    <CohortDescriptionInput onChange={onChangeDescription} />
                </div>
                <div style={{ flex: 4, marginLeft: 20 }} />
            </div>

            <Divider />

            <CohortMatchingCriteriaSection />
        </div>
    )
}
