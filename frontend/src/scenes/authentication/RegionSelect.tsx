import React from 'react'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonSelect } from '@posthog/lemon-ui'
import { Region } from '~/types'
import { CLOUD_HOSTNAMES, FEATURE_FLAGS } from 'lib/constants'
import { router } from 'kea-router'

import { PureField } from 'lib/forms/Field'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const RegionSelect = (): JSX.Element | null => {
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.REGION_SELECT] || !preflight?.cloud || !preflight?.region) {
        return null
    }
    return (
        <PureField label="Data region">
            <LemonSelect
                onChange={(region) => {
                    if (!region) {
                        return
                    }
                    const { pathname, search, hash } = router.values.currentLocation
                    const newUrl = `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
                    window.location.href = newUrl
                }}
                value={preflight?.region}
                options={[
                    {
                        label: 'United States',
                        value: Region.US,
                    },
                    {
                        label: 'European Union',
                        value: Region.EU,
                    },
                ]}
                fullWidth
            />
        </PureField>
    )
}

export default RegionSelect
