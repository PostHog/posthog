import './LEGACY_InsightTooltip.scss'

import clsx from 'clsx'
import { DateDisplay } from 'lib/components/DateDisplay'
import { IconHandClick } from 'lib/lemon-ui/icons'

import { IntervalType } from '~/types'

interface BodyLine {
    id?: string | number
    component: React.ReactNode
}

interface InsightTooltipProps {
    altTitle?: string | JSX.Element | null // Alternate string to display as title (in case date reference is not available or not desired)
    referenceDate?: string
    interval?: IntervalType
    bodyLines?: BodyLine[] // bodyLines is in here for its similarity to LineChart's built-in tooltips, but children is easier to use in other React components
    inspectPersonsLabel?: boolean
    children?: React.ReactNode
    preferAltTitle?: boolean // Whether `altTitle` should be prefered over the default DateDisplay to show as header of the tooltip
    hideHeader?: boolean
}

export function LEGACY_InsightTooltip({
    altTitle,
    referenceDate,
    interval,
    bodyLines = [],
    inspectPersonsLabel,
    children,
    preferAltTitle,
    hideHeader,
}: InsightTooltipProps): JSX.Element {
    return (
        <div className={clsx('max-w-80', `inner-tooltip${bodyLines.length > 1 ? ' multiple' : ''}`)}>
            {!hideHeader && (
                <header>
                    {referenceDate && interval && !preferAltTitle ? (
                        <DateDisplay interval={interval} date={referenceDate} />
                    ) : (
                        altTitle
                    )}
                </header>
            )}
            {bodyLines?.length > 0 && (
                <ul>
                    {bodyLines.map((line, index) => (
                        <li key={line.id ?? index}>{line.component}</li>
                    ))}
                </ul>
            )}
            {children}
            {inspectPersonsLabel && (
                <div className="inspect-persons-label">
                    <IconHandClick />
                    Click on data point to view persons or groups
                </div>
            )}
        </div>
    )
}
