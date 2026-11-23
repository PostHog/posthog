import { LemonCard } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { ChannelsSection } from '../../scenes/settings/ChannelsSection'
import { QuillSupportChannelsSettings } from '../QuillSupportChannelsSettings/QuillSupportChannelsSettings'
import { WebAndApiAccessSettings } from '../WebAndApiAccessSettings/WebAndApiAccessSettings'

export function SupportChannelsSettings(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillSupportChannelsSettings />
    }

    return (
        <>
            <SceneSection
                title="Channels"
                className="my-8"
                description="Choose where customers can reach you. Each channel can be configured independently."
            >
                <LemonCard hoverEffect={false} className="max-w-[800px] px-4 py-3">
                    <ChannelsSection />
                </LemonCard>
            </SceneSection>
            <WebAndApiAccessSettings />
        </>
    )
}
