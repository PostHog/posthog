import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getExceptionAttributes } from 'scenes/error-tracking/utils'

export const Overview = (): JSX.Element => {
    const { properties, propertiesLoading } = useValues(errorTrackingIssueSceneLogic)

    if (propertiesLoading) {
        return (
            <div className="space-y-2 p-2">
                <LemonSkeleton />
                <LemonSkeleton.Row repeat={2} />
            </div>
        )
    }

    const { synthetic, level, browser, os, library, unhandled } = getExceptionAttributes(properties)
    return (
        <div className="grid grid-cols-2 gap-2">
            {[
                { label: 'Level', value: level },
                { label: 'Synthetic', value: synthetic },
                { label: 'Library', value: library },
                { label: 'Unhandled', value: unhandled },
                { label: 'Browser', value: browser },
                { label: 'OS', value: os },
                { label: 'URL', value: properties['$current_url'] },
            ]
                .filter((row) => row.value !== undefined)
                .map((row, index) => (
                    <div key={index} className="flex items-center justify-between">
                        <span className="font-semibold w-full">{row.label}</span>
                        <span className="w-full truncate" title={row.value}>
                            {row.value + ''}
                        </span>
                    </div>
                ))}
        </div>
    )
}
