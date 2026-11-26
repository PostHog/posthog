import { LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import type { OrganizationSelectorProps } from './types'
import { createOrganizationOption, organizationTooltip } from './utils'

export const OrganizationSelector = ({
    organizations,
    mode,
    value,
    onChange,
}: OrganizationSelectorProps): JSX.Element =>
    mode === 'single' ? (
        <LemonSelect
            fullWidth
            data-attr="organizations"
            value={value?.[0]}
            onChange={(organizationId) => onChange?.(organizationId ? [organizationId] : [])}
            options={organizations.map((org) => ({
                value: org.id,
                label: org.name,
                tooltip: organizationTooltip(org),
            }))}
            loading={organizations === undefined}
            placeholder="Select an organization..."
        />
    ) : (
        <LemonInputSelect
            mode="multiple"
            data-attr="organizations"
            value={value}
            onChange={onChange}
            options={organizations.map((org) => createOrganizationOption(org)) ?? []}
            loading={organizations === undefined}
            placeholder="Select organizations..."
        />
    )
