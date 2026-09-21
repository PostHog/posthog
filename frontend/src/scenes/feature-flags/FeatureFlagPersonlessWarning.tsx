import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { AnyPropertyFilter } from '~/types'

import { PersonlessReason, featureFlagPersonlessWarningLogic } from './featureFlagPersonlessWarningLogic'

const REASON_COPY: Record<PersonlessReason, string> = {
    'project-opt-out': 'Person processing is off for this project, so no events store a person profile.',
    'ingestion-restriction':
        "An ingestion restriction turns off person processing for some of this project's events, so those events store no person profile.",
}

export interface FeatureFlagPersonlessWarningProps {
    properties: AnyPropertyFilter[]
}

export function FeatureFlagPersonlessWarning({ properties }: FeatureFlagPersonlessWarningProps): JSX.Element | null {
    const { personlessReason, storedPropertyKeys, targetsCohort } = useValues(
        featureFlagPersonlessWarningLogic({ properties })
    )

    if (!personlessReason || (storedPropertyKeys.length === 0 && !targetsCohort)) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-2">
            <p className="font-semibold mb-1">These conditions can't match without a person profile</p>
            <p className="mb-1">{REASON_COPY[personlessReason]}</p>
            {storedPropertyKeys.length > 0 && (
                <p className="mb-1">
                    These conditions read stored person properties:{' '}
                    {storedPropertyKeys.map((key, index) => (
                        <span key={key}>
                            {index > 0 ? ', ' : ''}
                            <code>{key}</code>
                        </span>
                    ))}
                    . Send the values with <code>setPersonPropertiesForFlags</code> in client SDKs, or{' '}
                    <code>personProperties</code> in server SDKs, before you evaluate the flag.
                </p>
            )}
            {targetsCohort && (
                <p className="mb-1">
                    Cohort membership is also read from stored person data, so cohort conditions do not match either.
                </p>
            )}
            <Link to="https://posthog.com/docs/libraries/js/usage#overriding-server-properties">Learn more</Link>
        </LemonBanner>
    )
}
