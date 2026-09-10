import { IconCheck, IconX } from '@posthog/icons'
import { LemonColorGlyph, Link, ProfilePicture } from '@posthog/lemon-ui'

import { DataColorToken } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { formatCustomPropertyValue } from '../../CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import type { AccountSidebarProperty } from './accountPropertyTypes'

export interface AccountPropertyValueProps {
    property: AccountSidebarProperty
}

export function AccountPropertyValue({ property }: AccountPropertyValueProps): JSX.Element {
    if (property.kind === 'relationship') {
        if (property.members.length === 0) {
            return <span className="text-sm text-muted">Unassigned</span>
        }

        return (
            <div className="flex flex-col gap-1 min-w-0">
                {property.members.map((member) => (
                    <span key={member.id} className="inline-flex items-center gap-2 min-w-0">
                        <ProfilePicture user={{ email: member.email }} size="sm" />
                        <span className="text-sm font-medium truncate" title={member.email}>
                            {member.name || member.email}
                        </span>
                    </span>
                ))}
            </div>
        )
    }

    const { definition, value } = property
    if (value === null || value === '') {
        return <span className="text-sm text-muted">Not set</span>
    }

    const raw = String(value)
    if (definition.display_type === 'boolean') {
        const isTrue = value === true || raw === 'true'
        return (
            <span className="inline-flex items-center gap-1 text-sm font-medium">
                {isTrue ? <IconCheck className="text-success" /> : <IconX className="text-danger" />}
                {isTrue ? 'Yes' : 'No'}
            </span>
        )
    }
    if (definition.display_type === 'link') {
        return (
            <Link to={raw} target="_blank" className="text-sm font-medium truncate">
                {raw}
            </Link>
        )
    }
    if (definition.display_type === 'date' || definition.display_type === 'datetime') {
        const parsed = dayjs(definition.display_type === 'date' ? raw.slice(0, 10) : raw)
        if (!parsed.isValid()) {
            return <span className="text-sm font-medium truncate">{raw}</span>
        }
        return definition.display_type === 'datetime' ? (
            <span className="text-sm font-medium">
                <TZLabel time={parsed} formatDate="MMM D, YYYY" formatTime="HH:mm" />
            </span>
        ) : (
            <span className="text-sm font-medium">{parsed.format('MMM D, YYYY')}</span>
        )
    }
    if (definition.display_type === 'select') {
        const option = definition.options?.find((candidate) => candidate.label === raw)
        return (
            <span className="inline-flex items-center gap-1.5 min-w-0 text-sm font-medium">
                {option ? <LemonColorGlyph colorToken={option.color as DataColorToken} size="small" /> : null}
                <span className="truncate">{raw}</span>
            </span>
        )
    }

    return (
        <span className="text-sm font-medium tabular-nums truncate">{formatCustomPropertyValue(raw, definition)}</span>
    )
}
