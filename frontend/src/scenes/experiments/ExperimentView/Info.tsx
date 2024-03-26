import '../Experiment.scss'

import { IconWarning } from '@posthog/icons'
import { Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ProgressStatus } from '~/types'

import { StatusTag } from '../Experiment'
import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { ResultsTag } from './components'

export function Info(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { created_by, created_at } = experiment

    if (!experiment.feature_flag) {
        return <></>
    }

    return (
        <div className="flex">
            <div className="w-1/2 inline-flex space-x-8">
                <div className="block">
                    <div className="text-xs font-semibold uppercase tracking-wide">Status</div>
                    <StatusTag experiment={experiment} />
                </div>
                <div className="block">
                    <div className="text-xs font-semibold uppercase tracking-wide">Significance</div>
                    <ResultsTag />
                </div>
                {experiment.feature_flag && (
                    <div className="block">
                        <div className="text-xs font-semibold uppercase tracking-wide">
                            <span>Feature flag</span>
                        </div>
                        {getExperimentStatus(experiment) === ProgressStatus.Running &&
                            !experiment.feature_flag.active && (
                                <Tooltip
                                    placement="bottom"
                                    title="Your experiment is running, but the linked flag is disabled. No data is being collected."
                                >
                                    <IconWarning
                                        style={{ transform: 'translateY(2px)' }}
                                        className="mr-1 text-danger"
                                        fontSize="18px"
                                    />
                                </Tooltip>
                            )}
                        <CopyToClipboardInline
                            iconStyle={{ color: 'var(--lemon-button-icon-opacity)' }}
                            className="font-normal text-sm"
                            description="feature flag key"
                        >
                            {experiment.feature_flag.key}
                        </CopyToClipboardInline>
                        <Link
                            target="_blank"
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            <IconOpenInNew fontSize="18" />
                        </Link>
                    </div>
                )}
            </div>

            <div className="w-1/2 flex flex-col justify-end">
                <div className="ml-auto inline-flex space-x-8">
                    <div className="block">
                        <div className="text-xs font-semibold uppercase tracking-wide">Created at</div>
                        {created_at && <TZLabel time={created_at} />}
                    </div>
                    <div className="block">
                        <div className="text-xs font-semibold uppercase tracking-wide">Created by</div>
                        {created_by && <ProfilePicture user={created_by} size="md" showName />}
                    </div>
                </div>
            </div>
        </div>
    )
}
