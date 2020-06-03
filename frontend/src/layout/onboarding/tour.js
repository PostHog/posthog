import React from 'react'
import Tour from 'reactour'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { onboardingLogic, TourType } from './onboardingLogic'

export function PGTour() {
    const { tourActive, tourType, tourStep } = useValues(onboardingLogic)
    const { setTourFinish, setTourStep } = useActions(onboardingLogic)
    return (
        <Tour
            steps={determineTour(tourType)}
            lastStepNextButton={<Button type="primary">Done</Button>}
            isOpen={tourActive}
            onRequestClose={() => {
                setTourFinish()
                setTourStep(0)
            }}
            goToStep={tourStep}
            nextStep={() => setTourStep(tourStep + 1)}
            prevStep={() => setTourStep(tourStep - 1)}
            startAt={tourStep}
        />
    )
}

function determineTour(type) {
    if (type === TourType.TRENDS) return trendsTour
    else if (type === TourType.FUNNEL) return funnelTour
    else []
}

const trendsTour = [
    {
        selector: '[data-attr="trend-sidebar-editor"]',
        content: 'This is the trend editor',
        stepInteraction: false,
    },
    {
        selector: '[data-attr="action-filter"]',
        content: 'You can add actions and events you want to see data for',
        stepInteraction: false,
    },
    {
        selector: '[data-attr="prop-filters"]',
        content:
            'This is an optional filter you can add to specify properties on the actions and events you want to view.',
        stepInteraction: false,
    },
    {
        selector: '[data-attr="trends-viz"]',
        content: 'Your data metrics will change accordingly',
        stepInteraction: false,
    },
    {
        selector: '[data-attr="save-to-dashboard-button"]',
        content: 'Once you have added actions and events you can save this to your dashboards',
        stepInteraction: false,
    },
]

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
