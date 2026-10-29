import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { activityClientLabel } from 'lib/components/ActivityLog/activityClientLabel'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagBasicType } from '~/types'

import {
    RESTORE_UNAVAILABLE_DISABLED_REASON,
    canRestoreFeatureFlag,
} from 'products/feature_flags/frontend/featureFlagConfigFormat'

import { experimentLogic } from '../experimentLogic'
import { deletedFlagBannerLogic } from './deletedFlagBannerLogic'

// Deleting a flag that an experiment uses renames its key to `<key>:deleted:<id>`. People know the flag by the original key.
function keyBeforeDelete(flag: FeatureFlagBasicType): string {
    const suffix = `:deleted:${flag.id}`
    return flag.key.endsWith(suffix) ? flag.key.slice(0, -suffix.length) : flag.key
}

function DeletedFlagBannerContent({
    experimentId,
    flag,
}: {
    experimentId: Experiment['id']
    flag: FeatureFlagBasicType
}): JSX.Element {
    const logic = deletedFlagBannerLogic({ experimentId, flagId: flag.id })
    const { flagDeletion, restoredFlagLoading } = useValues(logic)
    const { restoreFlag } = useActions(logic)
    const canRestore = canRestoreFeatureFlag(flag.filters)

    const flagLink = (
        <Link to={urls.featureFlag(flag.id)} target="_blank">
            {keyBeforeDelete(flag)}
        </Link>
    )

    return (
        <LemonBanner
            type="error"
            className="mb-4"
            action={
                canRestore
                    ? {
                          children: 'Restore flag',
                          onClick: restoreFlag,
                          loading: restoredFlagLoading,
                          'data-attr': 'experiment-restore-deleted-flag',
                      }
                    : undefined
            }
        >
            <div>
                <strong>This experiment's feature flag is deleted</strong>
            </div>
            <div>
                {flagDeletion?.actor ? (
                    <>
                        {flagDeletion.actor} deleted {flagLink} <TZLabel time={flagDeletion.deletedAt} />
                        {flagDeletion.client ? ` via ${activityClientLabel(flagDeletion.client)}` : ''}.
                    </>
                ) : (
                    <>The feature flag {flagLink} was deleted.</>
                )}{' '}
                The experiment can't launch until the flag is restored.
                {!canRestore && <> {RESTORE_UNAVAILABLE_DISABLED_REASON}</>}
            </div>
        </LemonBanner>
    )
}

/** A draft can't launch on a deleted flag. Once an experiment has run, deleting its flag is the normal cleanup. */
export function DeletedFlagBanner(): JSX.Element | null {
    const { experiment, isExperimentDraft } = useValues(experimentLogic)
    const flag = experiment.feature_flag

    if (!flag?.deleted || !isExperimentDraft) {
        return null
    }

    return <DeletedFlagBannerContent experimentId={experiment.id} flag={flag} />
}
