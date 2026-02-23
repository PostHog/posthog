import { IconInfo, IconWarning } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'

import type { Finding, GuidanceDoc, HogSenseSeverity } from './types'

export function severityColor(severity: HogSenseSeverity): string {
    switch (severity) {
        case 'warning':
            return 'text-warning'
        case 'error':
            return 'text-danger'
        case 'info':
        default:
            return 'text-secondary'
    }
}

export function SeverityIcon({ severity }: { severity: HogSenseSeverity }): JSX.Element {
    switch (severity) {
        case 'warning':
        case 'error':
            return <IconWarning className="text-base shrink-0" />
        case 'info':
        default:
            return <IconInfo className="text-base shrink-0" />
    }
}

function DocLinks({ docs }: { docs: GuidanceDoc[] }): JSX.Element | null {
    if (docs.length === 0) {
        return null
    }

    return (
        <>
            {' Use '}
            {docs.map((doc, i) => {
                const isLast = i === docs.length - 1
                const isSecondToLast = i === docs.length - 2
                return (
                    <span key={doc.url}>
                        <Link to={doc.url} target="_blank" className={`text-xs${doc.mono ? ' font-mono' : ''}`}>
                            {doc.label}
                        </Link>
                        {!isLast && (isSecondToLast && docs.length > 1 ? ' or ' : ', ')}
                    </span>
                )
            })}
            .
        </>
    )
}

export function HogSenseTooltipContent({ finding }: { finding: Finding }): JSX.Element {
    return (
        <span className="text-xs">
            {finding.description}
            {finding.docs && finding.docs.length > 0 && <DocLinks docs={finding.docs} />}
        </span>
    )
}
