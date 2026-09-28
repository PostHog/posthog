import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

export function ResourceAccessControlHint({ onNavigate }: { onNavigate: () => void }): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const hasAccessControl = hasAvailableFeature(AvailableFeature.ACCESS_CONTROL)

    return (
        <div className="mt-4 p-3 rounded border border-primary bg-surface-secondary text-left">
            <p className="mb-1 font-semibold">Only need to restrict a few tables or members?</p>
            <p className="mb-0">
                <span>
                    {hasAccessControl
                        ? 'Your plan already lets you set access rules for one resource or one member, without roles.'
                        : 'The Boost plan lets you set access rules for one resource or one member, without roles.'}
                </span>{' '}
                <Link
                    to={urls.settings('environment-access-control')}
                    data-attr="upgrade-modal-resource-access-hint"
                    onClick={() => {
                        posthog.capture('upgrade modal resource access hint clicked', {
                            featureName: AvailableFeature.ROLE_BASED_ACCESS,
                            has_access_control: hasAccessControl,
                        })
                        onNavigate()
                    }}
                >
                    Set resource access rules
                </Link>
            </p>
        </div>
    )
}
