import { useValues, useActions } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'
import { CardContainer } from '../CardContainer'
import { ingestionLogic } from '../ingestionLogic'

export function ThirdPartyPanel(): JSX.Element {
    const { index } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)

    return (
        <CardContainer
            index={index}
            showFooter={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            <div>
                <LemonButton>Segment</LemonButton>
                <LemonButton>Rudderstack</LemonButton>
                <LemonButton>Redshift (beta)</LemonButton>
            </div>
        </CardContainer>
    )
}
