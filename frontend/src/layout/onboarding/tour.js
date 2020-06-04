import React from 'react'
import Tour from 'reactour'
import { useValues, useActions } from 'kea'
import { onboardingLogic, TourType } from './onboardingLogic'

export function PGTour() {
    const { tourActive, tourType, tourStep } = useValues(onboardingLogic)
    const { setTourFinish, setTourStep } = useActions(onboardingLogic)
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
            }}
            prevStep={() => setTourStep(tourStep - 1)}
            startAt={tourStep}
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
    return <div style={{ marginTop: 15, fontWeight: 600, fontSize: 16 }}>{props.children}</div>
}

const actionTour = [
    {
        selector: '[data-attr="action-editor"]',
        content: () => (
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
        action: node => {
            node.click()
        },
        stepInteraction: false,
    },
    {
        selector: '[data-attr="action-edit-frontend-element"]',
        content: (
            <ToolTipText>
                {
                    'For example, adding an action by frontend element means that you can filter for a specific element thats being autocaptured'
                }
            </ToolTipText>
        ),
        action: node => {
            node.click()
        },
        stepInteraction: false,
    },
    {
        selector: '[data-attr="action-editor-card"]',
        content: (
            <ToolTipText>
                {'You can manually enter details on a frontend element that you can to filter for'}
            </ToolTipText>
        ),
        stepInteraction: false,
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
        selector: '[data-attr="save-action-button"]',
        content: (
            <ToolTipText>
                {
                    "Once you're satisfied with the action and have given it a name, you can save it and use it in your analyses"
                }
            </ToolTipText>
        ),
        stepInteraction: false,
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
        stepInteraction: false,
    },
    {
        selector: '[data-attr="action-filter"]',
        content: <ToolTipText>{'You can add actions and events you want to see data for'}</ToolTipText>,
        stepInteraction: false,
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
        stepInteraction: false,
    },
    {
        selector: '[data-attr="save-to-dashboard-button"]',
        content: (
            <ToolTipText>{'Once you have added actions and events you can save this to your dashboards'}</ToolTipText>
        ),
        stepInteraction: false,
    },
]

const funnelTour = [
    {
        selector: '[data-attr="edit-funnel"]',
        content: <ToolTipText>{'This is the funnel editor'}</ToolTipText>,
        stepInteraction: false,
    },
    {
        selector: '[data-attr="funnel-editor-required-fields"]',
        content: (
            <ToolTipText>
                {
                    'Your funnel steps will be determined by the actions and events that you add here. You will also be required to enter a name for you funnel.'
                }
            </ToolTipText>
        ),
        stepInteraction: false,
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
        stepInteraction: false,
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
        stepInteraction: false,
    },
]
