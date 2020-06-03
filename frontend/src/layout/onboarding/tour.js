import React from 'react'
import Tour from 'reactour'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { onboardingLogic } from './onboardingLogic'

export function PGTour() {
    const { tourActive } = useValues(onboardingLogic)
    const { setTourFinish } = useActions(onboardingLogic)
    return (
        <Tour
            steps={funnelTour}
            lastStepNextButton={<Button type="primary">Done</Button>}
            isOpen={tourActive}
            onRequestClose={() => setTourFinish()}
            goToStep={1}
        />
    )
}

const funnelTour = [
    {
        selector: '[data-attr="edit-funnel"]',
        content: 'This is the funnel editor',
        stepInteraction: false,
    },
    {
        selector: '[data-attr="funnel-editor-required-fields"]',
        content:
            'Your funnel steps will be determined by the actions and events that you add here. You will also be required to enter a name for you funnel.',
        stepInteraction: false,
    },
    {
        selector: '[data-attr="prop-filters"]',
        content:
            'This is an optional filter you can add to specify properties on the actions and events you want to view.',
        stepInteraction: false,
    },
    {
        selector: '[data-attr="save-funnel-button"]',
        content:
            'Once you have added actions and events and provided a title for your funnel you save it and your funnel will be calculated and displayed',
        stepInteraction: false,
    },
]
