import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { SSOProvider } from '~/types'

import { ssoSelectOptions } from './ssoSelectOptions'

export interface SSOSelectInterface {
    value: SSOProvider | ''
    loading: boolean
    onChange: (value: SSOProvider | '') => void
    samlAvailable: boolean
    oidcAvailable?: boolean
    disabledReason?: string | null
}

export function SSOSelect({
    value,
    loading,
    onChange,
    samlAvailable,
    oidcAvailable,
    disabledReason,
}: SSOSelectInterface): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!preflight) {
        return null
    }

    const options = ssoSelectOptions(preflight, samlAvailable, oidcAvailable, value, featureFlags)

    return (
        <LemonSelect
            value={value}
            options={options}
            loading={loading}
            disabledReason={loading ? 'Cannot change while loading' : disabledReason}
            fullWidth
            onChange={onChange}
        />
    )
}
