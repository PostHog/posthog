import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonColorGlyph } from '@posthog/lemon-ui'

import type { DataColorToken } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { formatCustomPropertyValue } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import { getCanonicalPropertyTab } from './accountCustomPropertyDisplay'
import type { AccountColumnDisplayConfig } from './accountsColumnConfigLogic'
import { AccountExpansionTab, accountsExpansionLogic } from './accountsExpansionLogic'
import { CustomPropertyHistoryCell } from './CustomPropertyHistoryCell'

function CanonicalTimestampCell({
    accountId,
    definition,
    value,
    tab,
}: {
    accountId: string
    definition: CustomPropertyDefinitionApi
    value: string
    tab: AccountExpansionTab
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openAccountTab } = useActions(accountsExpansionLogic)
    const label = <TZLabel time={value} showSeconds={definition.display_type === 'datetime'} />
    return (
        <Link
            to={urls.customerAnalyticsAccount(accountId, tab)}
            onClick={(event) => {
                if (
                    featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE] ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey
                ) {
                    return
                }
                event.preventDefault()
                event.stopPropagation()
                openAccountTab(accountId, tab)
            }}
        >
            {label}
        </Link>
    )
}

function CustomPropertyValue({
    accountId,
    value,
    definition,
}: {
    accountId?: string
    value: string
    definition: CustomPropertyDefinitionApi
}): JSX.Element {
    if (!value) {
        return <span className="text-muted">—</span>
    }
    if (definition.display_type === 'date' || definition.display_type === 'datetime') {
        const tab = getCanonicalPropertyTab(definition)
        if (tab && accountId) {
            return <CanonicalTimestampCell accountId={accountId} definition={definition} value={value} tab={tab} />
        }
        return <TZLabel time={value} showSeconds={definition.display_type === 'datetime'} />
    }
    if (definition.display_type === 'boolean') {
        return value === 'true' || value === '1' ? <IconCheck /> : <IconX className="text-muted" />
    }
    if (definition.display_type === 'link') {
        return (
            <Link to={value} target="_blank" targetBlankIcon={false}>
                {value}
            </Link>
        )
    }
    if (definition.display_type === 'select') {
        const option = definition.options?.find((candidate) => candidate.label === value)
        return (
            <span className="inline-flex items-center gap-1.5">
                {option && <LemonColorGlyph colorToken={option.color as DataColorToken} size="small" />}
                <span>{value}</span>
            </span>
        )
    }
    return <span>{formatCustomPropertyValue(value, definition)}</span>
}

export interface CustomPropertyValueDisplayProps {
    /** A scalar value, or history points when `display` is set. */
    raw: unknown
    definition: CustomPropertyDefinitionApi
    display?: AccountColumnDisplayConfig
    /** Links canonical timestamps to their account tab. Without it they render as plain timestamps. */
    accountId?: string
}

export function CustomPropertyValueDisplay({
    raw,
    definition,
    display,
    accountId,
}: CustomPropertyValueDisplayProps): JSX.Element {
    if (display) {
        return <CustomPropertyHistoryCell raw={raw} definition={definition} display={display} />
    }
    return (
        <CustomPropertyValue
            accountId={accountId}
            value={raw === null || raw === undefined ? '' : String(raw)}
            definition={definition}
        />
    )
}
