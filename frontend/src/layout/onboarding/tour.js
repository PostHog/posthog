import React from 'react'
import Tour from 'reactour'
import { useValues, useActions } from 'kea'
import { onboardingLogic, TourType } from './onboardingLogic'
import { Button } from 'antd'

export function PGTour() {
    const { tourActive, tourType, tourStep } = useValues(onboardingLogic)
    const { setTourFinish, setTourStep, updateOnboardingStep } = useActions(onboardingLogic)

    function updateTourStatus(type, step) {
        const tourSteps = determineTour(type)
        if (step === tourSteps.length - 1) {
            if (type === TourType.ACTION) updateOnboardingStep(0)
            else if (type === TourType.TRENDS) updateOnboardingStep(1)
            else if (type === TourType.FUNNEL) updateOnboardingStep(2)
        }
    }

    return (
        <Tour
            steps={determineTour(tourType)}
            isOpen={tourActive}
            onRequestClose={() => {
                setTourFinish()
                setTourStep(0)
            }}
            goToStep={tourStep}
            nextStep={() => {
                setTourStep(tourStep + 1)
                updateTourStatus(tourType, tourStep + 1)
            }}
            prevStep={() => setTourStep(tourStep - 1)}
            startAt={tourStep}
            disableFocusLock
            lastStepNextButton={<Button type="primary">Done!</Button>}
        />
    )
}

function determineTour(type) {
    if (type === TourType.TRENDS) return trendsTour
    else if (type === TourType.FUNNEL) return funnelTour
    else if (type === TourType.ACTION) return actionTour
    else []
}

function ToolTipText(props) {
    return (
        <div data-attr="tour-tooltip" style={{ marginTop: 15, fontWeight: 600, fontSize: 16 }}>
            {props.children}
        </div>
    )
}

const actionTour = [
    {
        selector: '[data-attr="action-editor"]',
        content: (
            <ToolTipText>
                {
                    'This is the action editor that you can use to create actions on your events. Actions work like buckets by grouping events together.'
                }
            </ToolTipText>
        ),
        stepInteraction: false,
    },
    {
        selector: '[data-attr="action-edit-type-group"]',
        content: <ToolTipText>{'There are several different ways you can create an action'}</ToolTipText>,
        action: (node) => {
            node.click()
        },
    },
    {
        selector: '[data-attr="action-edit-frontend-element"]',
        content: (
            <ToolTipText>
                {
                    "For example, adding an action by frontend element means that you can filter for a specific element that's being autocaptured."
                }
            </ToolTipText>
        ),
        action: (node) => {
            node.click()
        },
        stepInteraction: false,
    },
    {
        selector: '[data-attr="action-editor-card"]',
        content: (
            <ToolTipText>
                {
                    'You can manually enter details on a frontend element that you can to filter for. Enter the details to an element on your site!'
                }
            </ToolTipText>
        ),
    },
    {
        selector: '[data-attr="action-editor-inspect-button"]',
        content: <ToolTipText>{'Or use our interactive tool to visually choose an element on your site!'}</ToolTipText>,
        stepInteraction: false,
    },
    {
        selector: '[data-attr="match-group-button"]',
        content: (
            <ToolTipText>{'If you want to combine more events in this action you can add a match group'}</ToolTipText>
        ),
        stepInteraction: false,
    },
    {
        selector: '[data-attr="edit-action-input"]',
        content: <ToolTipText>{'Give your action a name. What are your users doing here?'}</ToolTipText>,
    },
    {
        selector: '[data-attr="save-action-button"]',
        content: (
            <ToolTipText>
                {
                    "Once you're satisfied with the action and have given it a name, you can save it and use it in your analyses"
                }
            </ToolTipText>
        ),
    },
]

const trendsTour = [
    {
        selector: '[data-attr="trend-sidebar-editor"]',
        content: (
            <ToolTipText>
                {"This is the trend editor. You're changes will automatically update the visualization."}
            </ToolTipText>
        ),
    },
    {
        selector: '[data-attr="action-filter"]',
        content: <ToolTipText>{'You can add actions and events you want to see data for'}</ToolTipText>,
    },
    {
        selector: '[data-attr="trends-viz"]',
        content: (
            <ToolTipText>
                {
                    'Your can see the visualization here and make adjustments to the scale or interval using the toolbar above'
                }
            </ToolTipText>
        ),
    },
    {
        selector: '[data-attr="save-to-dashboard-button"]',
        content: (
            <ToolTipText>{'Once you have added actions and events you can save this to your dashboards'}</ToolTipText>
        ),
    },
]

const funnelTour = [
    {
        selector: '[data-attr="edit-funnel"]',
        content: <ToolTipText>{'This is the funnel editor'}</ToolTipText>,
    },
    {
        selector: '[data-attr="funnel-editor-required-fields"]',
        content: (
            <ToolTipText>
                {
                    'Your funnel steps will be determined by the actions and events that you add here. You will also be required to enter a name for your funnel.'
                }
            </ToolTipText>
        ),
    },
    {
        selector: '[data-attr="prop-filters"]',
        content: (
            <ToolTipText>
                {
                    'This is an optional filter you can add to specify properties on the actions and events you want to view.'
                }
            </ToolTipText>
        ),
    },
    {
        selector: '[data-attr="save-funnel-button"]',
        content: (
            <ToolTipText>
                {
                    'Once you have added actions and events and provided a title for your funnel you save it and your funnel will be calculated and displayed'
                }
            </ToolTipText>
        ),
    },
]
