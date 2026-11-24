import './Today.scss'

import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Skeleton } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { computeIsSelfDrivingSetUp } from 'products/signals/frontend/inbox/logics/inboxOnboardingLogic'
import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'
import { signalSourcesLogic } from 'products/signals/frontend/inbox/signalSourcesLogic'

import { TodayRow } from './TodayRow'
import { TodaySelfDrivingRow } from './TodaySelfDrivingRow'

function QuietRows({ quietRow }: { quietRow: ReactNode }): JSX.Element {
    return (
        <ol className="TodayRows" data-attr="today-for-you-empty">
            <TodaySelfDrivingRow />
            {quietRow}
        </ol>
    )
}

export function TodaySelfDrivingStatus({ quietRow }: { quietRow: ReactNode }): JSX.Element {
    if (!useFeatureFlag('PRODUCT_AUTONOMY')) {
        return <QuietRows quietRow={quietRow} />
    }
    return <TodaySelfDrivingVerdict quietRow={quietRow} />
}

function TodaySelfDrivingVerdict({ quietRow }: { quietRow: ReactNode }): JSX.Element {
    const { sourceConfigs, sourceConfigsLoadFailed, enabledSourcesCount } = useValues(signalSourcesLogic)
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutFleetLogic)

    if ((sourceConfigs === null && !sourceConfigsLoadFailed) || (scoutConfigs === null && scoutConfigsLoading)) {
        return <Skeleton className="h-12 w-full" />
    }
    if (!computeIsSelfDrivingSetUp(enabledSourcesCount, scoutConfigs ?? [])) {
        return <QuietRows quietRow={quietRow} />
    }
    return (
        <ol className="TodayRows">
            <TodayRow
                tone="quiet"
                icon={{ glyph: <IconSparkles /> }}
                title="Self-driving is reviewing your data"
                facts={['Reports show here when it finds something that needs you']}
                to={urls.inbox()}
                dataAttr="today-self-driving-status"
            />
        </ol>
    )
}
