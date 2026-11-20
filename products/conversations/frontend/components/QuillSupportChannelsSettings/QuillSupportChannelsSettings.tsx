import { Card, CardContent } from '@posthog/quill'

import { ChannelsSection } from '../../scenes/settings/ChannelsSection'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { WebAndApiAccessSettings } from '../WebAndApiAccessSettings/WebAndApiAccessSettings'

export function QuillSupportChannelsSettings(): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <QuillSettingsSubsection
                title="Channels"
                description="Choose where customers can reach you. Each channel can be configured independently."
            >
                <Card size="sm" className="max-w-200">
                    <CardContent>
                        <ChannelsSection />
                    </CardContent>
                </Card>
            </QuillSettingsSubsection>
            <WebAndApiAccessSettings />
        </div>
    )
}
