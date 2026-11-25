import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconSelfDriving } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { computeIsSelfDrivingSetUp } from 'products/signals/frontend/inbox/logics/inboxOnboardingLogic'
import { scoutNamesLogic } from 'products/signals/frontend/inbox/logics/scoutNamesLogic'
import { signalSourcesLogic } from 'products/signals/frontend/inbox/signalSourcesLogic'

import { TodayPromptItem } from './TodayPromptItem'
import { todayPromptsLogic } from './todayPromptsLogic'

const SELF_DRIVING_ICON = { color: 'var(--color-product-self-driving-light)', glyph: <IconSelfDriving /> }

export function TodaySelfDrivingRow(): JSX.Element | null {
    const { canOfferSelfDriving } = useValues(todayPromptsLogic)

    if (!canOfferSelfDriving) {
        return null
    }
    return <SelfDrivingSetUpCheck />
}

function SelfDrivingSetUpCheck(): JSX.Element | null {
    const { sourceConfigs, sourceConfigsLoadFailed, enabledSourcesCount, hasEmittingScanner } =
        useValues(signalSourcesLogic)
    const { scoutConfigs } = useValues(scoutNamesLogic)

    if (sourceConfigs === null || sourceConfigsLoadFailed || hasEmittingScanner === null || scoutConfigs === null) {
        return null
    }
    if (computeIsSelfDrivingSetUp(enabledSourcesCount, scoutConfigs)) {
        return null
    }
    return <SelfDrivingPrompt />
}

function SelfDrivingPrompt(): JSX.Element {
    const { dismissPrompt, reportPromptShown } = useActions(todayPromptsLogic)

    useOnMountEffect(() => reportPromptShown('self_driving'))

    return (
        <TodayPromptItem
            icon={SELF_DRIVING_ICON}
            title="Self-driving isn’t set up in this project yet"
            meta="It reviews your data each day and adds a report here when something needs you."
            dataAttr="today-self-driving-row"
            actions={
                <>
                    <Button
                        size="sm"
                        variant="link-muted"
                        onClick={() => dismissPrompt('self_driving')}
                        data-attr="today-self-driving-row-dismiss"
                    >
                        Not now
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        render={<LinkPrimitive to={urls.inbox()} />}
                        data-attr="today-self-driving-row-set-up"
                    >
                        Set up self-driving
                    </Button>
                </>
            }
        />
    )
}
