import { LemonSelect } from '@posthog/lemon-ui'

import { LemonLabel } from '~/lib/lemon-ui/LemonLabel'
import { WebStatsBreakdown } from '~/queries/schema/schema-general'

export interface WebAnalyticsBreakdownSelectorProps {
    value: WebStatsBreakdown
    onChange: (value: WebStatsBreakdown) => void
}

const BREAKDOWN_OPTIONS = [
    {
        label: 'Paths',
        options: [
            { value: WebStatsBreakdown.Page, label: 'Path' },
            { value: WebStatsBreakdown.InitialPage, label: 'Initial Path' },
            { value: WebStatsBreakdown.ExitPage, label: 'Exit Path' },
        ],
    },
    {
        label: 'Sources',
        options: [
            { value: WebStatsBreakdown.InitialChannelType, label: 'Channel' },
            { value: WebStatsBreakdown.InitialReferringDomain, label: 'Referring Domain' },
            { value: WebStatsBreakdown.InitialUTMSource, label: 'UTM Source' },
            { value: WebStatsBreakdown.InitialUTMCampaign, label: 'UTM Campaign' },
            { value: WebStatsBreakdown.InitialUTMMedium, label: 'UTM Medium' },
            { value: WebStatsBreakdown.InitialUTMContent, label: 'UTM Content' },
            { value: WebStatsBreakdown.InitialUTMTerm, label: 'UTM Term' },
            { value: WebStatsBreakdown.InitialUTMSourceMediumCampaign, label: 'Source / Medium / Campaign' },
        ],
    },
    {
        label: 'Devices',
        options: [
            { value: WebStatsBreakdown.Browser, label: 'Browser' },
            { value: WebStatsBreakdown.OS, label: 'OS' },
            { value: WebStatsBreakdown.DeviceType, label: 'Device Type' },
            { value: WebStatsBreakdown.Viewport, label: 'Viewport' },
        ],
    },
    {
        label: 'Geography',
        options: [
            { value: WebStatsBreakdown.Country, label: 'Country' },
            { value: WebStatsBreakdown.Region, label: 'Region' },
            { value: WebStatsBreakdown.City, label: 'City' },
            { value: WebStatsBreakdown.Timezone, label: 'Timezone' },
            { value: WebStatsBreakdown.Language, label: 'Language' },
        ],
    },
]

export function WebAnalyticsBreakdownSelector({ value, onChange }: WebAnalyticsBreakdownSelectorProps): JSX.Element {
    return (
        <>
            <div className="flex items-center justify-between gap-2">
                <LemonLabel info="Break down your Web Analytics data by different dimensions such as pages, traffic sources, devices, or geography to analyze patterns and trends.">
                    Breakdown by
                </LemonLabel>
            </div>
            <div className="flex flex-wrap gap-2 items-center">
                <LemonSelect
                    value={value}
                    onChange={onChange}
                    options={BREAKDOWN_OPTIONS}
                    placeholder="Select breakdown"
                />
            </div>
        </>
    )
}
