import { FunnelLayout, FunnelStepReference, FunnelVizType } from '~/types'
import { EntityType } from '~/types'
import { DataDrivenFunnel } from './DataDrivenFunnel'

/**
 * Example usage of DataDrivenFunnel component.
 * This shows how you can use the component with your own data instead of requiring a query.
 */
export function DataDrivenFunnelExample(): JSX.Element {
    // Example funnel data - this could come from experiments, API calls, or any other source
    const exampleFunnelSteps = [
        {
            action_id: 'step1',
            name: 'Visited Landing Page',
            custom_name: null,
            order: 0,
            count: 1000,
            type: EntityType.EVENTS,
            average_conversion_time: null,
            median_conversion_time: null,
            // No breakdown for this example
        },
        {
            action_id: 'step2', 
            name: 'Signed Up',
            custom_name: null,
            order: 1,
            count: 650,
            type: EntityType.EVENTS,
            average_conversion_time: 120, // 2 minutes
            median_conversion_time: 90,
            // Example with breakdown by source
            nested_breakdown: [
                {
                    action_id: 'step2',
                    name: 'Signed Up',
                    order: 1,
                    count: 400,
                    type: EntityType.EVENTS,
                    average_conversion_time: 110,
                    median_conversion_time: 85,
                    breakdown_value: 'organic',
                },
                {
                    action_id: 'step2',
                    name: 'Signed Up', 
                    order: 1,
                    count: 250,
                    type: EntityType.EVENTS,
                    average_conversion_time: 140,
                    median_conversion_time: 100,
                    breakdown_value: 'paid',
                },
            ],
        },
        {
            action_id: 'step3',
            name: 'Made First Purchase',
            custom_name: 'Converted to Customer',
            order: 2,
            count: 195,
            type: EntityType.EVENTS,
            average_conversion_time: 86400, // 1 day
            median_conversion_time: 43200, // 12 hours
            nested_breakdown: [
                {
                    action_id: 'step3',
                    name: 'Made First Purchase',
                    order: 2,
                    count: 130,
                    type: EntityType.EVENTS,
                    average_conversion_time: 72000,
                    median_conversion_time: 36000,
                    breakdown_value: 'organic',
                },
                {
                    action_id: 'step3',
                    name: 'Made First Purchase',
                    order: 2,
                    count: 65,
                    type: EntityType.EVENTS,
                    average_conversion_time: 108000,
                    median_conversion_time: 54000,
                    breakdown_value: 'paid',
                },
            ],
        },
    ]

    // Example time-to-convert data for histogram
    const exampleTimeConversionData = {
        bins: [
            [0, 50],    // 0-60s: 50 conversions
            [60, 120],  // 60-120s: 120 conversions
            [120, 200], // 120-180s: 200 conversions
            [180, 150], // 180-240s: 150 conversions
            [240, 80],  // 240-300s: 80 conversions
            [300, 30],  // 300-360s: 30 conversions
        ],
    }

    return (
        <div>
            <h2>DataDrivenFunnel Examples</h2>
            
            <div style={{ marginBottom: '2rem' }}>
                <h3>Vertical Steps Funnel</h3>
                <DataDrivenFunnel
                    steps={exampleFunnelSteps}
                    vizType={FunnelVizType.Steps}
                    layout={FunnelLayout.vertical}
                    stepReference={FunnelStepReference.total}
                    showPersonsModal={false}
                    inCardView={true}
                />
            </div>

            <div style={{ marginBottom: '2rem' }}>
                <h3>Horizontal Steps Funnel</h3>
                <DataDrivenFunnel
                    steps={exampleFunnelSteps}
                    vizType={FunnelVizType.Steps}
                    layout={FunnelLayout.horizontal}
                    stepReference={FunnelStepReference.previous}
                    showPersonsModal={false}
                    inCardView={true}
                />
            </div>

            <div style={{ marginBottom: '2rem' }}>
                <h3>Time to Convert Histogram</h3>
                <DataDrivenFunnel
                    steps={exampleFunnelSteps}
                    vizType={FunnelVizType.TimeToConvert}
                    timeConversionData={exampleTimeConversionData}
                    showPersonsModal={false}
                    inCardView={true}
                />
            </div>
        </div>
    )
}

/**
 * Helper function to convert experiment data to funnel steps format.
 * This shows how you might transform experiment results into the format needed by DataDrivenFunnel.
 */
export function convertExperimentDataToFunnelSteps(experimentData: any): any[] {
    // This is a placeholder - you would implement the actual conversion logic
    // based on your experiment data structure
    return [
        // Transform your experiment data here
        // For example:
        // {
        //     action_id: experiment.funnel_steps[0].action_id,
        //     name: experiment.funnel_steps[0].name,
        //     order: 0,
        //     count: experiment.results.control.step_counts[0],
        //     type: EntityType.EVENTS,
        //     breakdown_value: 'control',
        //     // ... other properties
        // }
    ]
}