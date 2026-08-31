import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonSwitchProps } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

const TEST_ACCOUNT_FILTER_TYPE_LABELS: Record<string, string> = {
    person: 'person property',
    cohort: 'cohort',
}

/**
 * Reason to disable the switch when the team has test account filters configured but none of them
 * apply to the current surface (e.g. only event-based filters, on a person-level cohort). Returns
 * null when the toggle is meaningful (a filter applies, or none are configured, which the empty
 * state handles separately). Keeps the toggle from being a silent no-op.
 */
export function getUnusedTestAccountFilterReason(
    filters: readonly { type?: string | null }[],
    applicableTypes: string[]
): string | null {
    if (filters.length === 0 || filters.some((filter) => filter.type && applicableTypes.includes(filter.type))) {
        return null
    }
    const labels = applicableTypes.map((type) => TEST_ACCOUNT_FILTER_TYPE_LABELS[type] ?? type)
    return `Only ${labels.join(' and ')} filters from your internal and test account settings apply here.`
}

type TestAccountFilterProps = Partial<LemonSwitchProps> & {
    checked: boolean
    onChange: (checked: boolean) => void
    /** When set, the toggle is disabled with an explanatory reason unless the team has at least one
     * test account filter of one of these types. Omit to accept every filter type (events etc.). */
    applicableFilterTypes?: string[]
}

export function TestAccountFilterSwitch({
    checked,
    onChange,
    applicableFilterTypes,
    ...props
}: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const filters = currentTeam?.test_account_filters || []
    const hasFilters = filters.length > 0
    const settingsUrl = urls.settings('environment-customization', 'internal-user-filtering')

    // With no filters configured the toggle does nothing, so a disabled switch just invites
    // clicks that never register. Send people to set the filters up instead. When the caller marks
    // the surface unusable (a data warehouse insight, a form mid-save), setup cannot help, so honor
    // that reason and keep the control disabled rather than promise a trip that changes nothing.
    if (!hasFilters) {
        return (
            <LemonButton
                type="secondary"
                size={props.size}
                data-attr={props['data-attr']}
                fullWidth={props.fullWidth}
                icon={<IconGear />}
                to={settingsUrl}
                targetBlank
                disabledReason={props.disabledReason}
                tooltip="Choose which users count as internal or test, then come back to filter them out. Opens in a new tab."
            >
                Set up internal and test user filtering
            </LemonButton>
        )
    }

    const unusedReason = applicableFilterTypes ? getUnusedTestAccountFilterReason(filters, applicableFilterTypes) : null
    return (
        <LemonSwitch
            bordered
            {...props}
            disabledReason={unusedReason ?? props.disabledReason}
            checked={checked}
            onChange={onChange}
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    {/* Opens in a new tab: this switch sits inside forms that hold unsaved work (a
                        half-built scanner, an unsaved cohort, an insight in progress). */}
                    <LemonButton
                        icon={<IconGear />}
                        size="small"
                        noPadding
                        className="ml-1"
                        to={settingsUrl}
                        targetBlank
                        hideExternalLinkIcon
                        tooltip="Configure internal and test users. Opens in a new tab."
                    />
                </div>
            }
        />
    )
}
