import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { SSFConfiguration } from './SSFConfiguration'

export function OrganizationSSF(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    return (
        <PayGateMini feature={AvailableFeature.SSF} featureDetail="organization-ssf">
            {!hasAvailableFeature(AvailableFeature.SSF) ? (
                <LemonBanner type="info">
                    Your plan does not include SSF.{' '}
                    <Link to={urls.organizationBilling()}>Review your billing plan</Link> to enable security event
                    sharing.
                </LemonBanner>
            ) : currentOrganization ? (
                <SSFConfiguration organizationId={currentOrganization.id} />
            ) : null}
        </PayGateMini>
    )
}
