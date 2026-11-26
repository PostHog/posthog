import './Today.scss'

import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Skeleton } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { computeIsSelfDrivingSetUp } from 'products/signals/frontend/inbox/logics/inboxOnboardingLogic'
import { scoutNamesLogic } from 'products/signals/frontend/inbox/logics/scoutNamesLogic'
import { signalSourcesLogic } from 'products/signals/frontend/inbox/signalSourcesLogic'

import { TodayRow } from './TodayRow'
import { TodaySelfDrivingRow } from './TodaySelfDrivingRow'

function QuietRows({ children }: { children: ReactNode }): JSX.Element {
    return (
        <ol className="TodayRows" data-attr="today-for-you-empty">
            {children}
        </ol>
    )
}

export function TodaySelfDrivingStatus({ quietRow }: { quietRow: ReactNode }): JSX.Element {
    if (!useFeatureFlag('PRODUCT_AUTONOMY')) {
        return <QuietRows>{quietRow}</QuietRows>
    }
    return <TodaySelfDrivingVerdict quietRow={quietRow} />
}

function TodaySelfDrivingVerdict({ quietRow }: { quietRow: ReactNode }): JSX.Element {
    const { sourceConfigs, sourceConfigsLoadFailed, enabledSourcesCount, hasEmittingScanner } =
        useValues(signalSourcesLogic)
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutNamesLogic)

    if (
        (sourceConfigs === null && !sourceConfigsLoadFailed) ||
        hasEmittingScanner === null ||
        (scoutConfigs === null && scoutConfigsLoading)
    ) {
        return <Skeleton className="h-12 w-full" />
    }
    if (!computeIsSelfDrivingSetUp(enabledSourcesCount, scoutConfigs ?? [])) {
        return (
            <QuietRows>
                <TodaySelfDrivingRow />
                {quietRow}
            </QuietRows>
        )
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
