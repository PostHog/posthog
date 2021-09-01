import React from 'react'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { toursLogic } from '~/toolbar/tours/toursLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'

export function StepsTab(): JSX.Element {
    const { setElementSelection } = useActions(toursLogic)
    const { params } = useValues(toursLogic)
    const { enableInspect } = useActions(elementsLogic)

    return (
        <div>
            {params?.steps &&
                params.steps.map((step, i) => (
                    <div
                        key={i}
                        style={{
                            borderRadius: '10px 0px 0px 10px',
                            backgroundColor: 'var(--border)',
                        }}
                    >
                        {step}
                    </div>
                ))}
            <Button
                onClick={() => {
                    setElementSelection(true)
                    enableInspect()
                }}
            >
                element selection
            </Button>
        </div>
    )
}
