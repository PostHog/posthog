import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { Dot, Text } from '@posthog/quill'

import { WaysToUsePreviewCallout } from './WaysToUsePreviewCallout'
import { WaysToUsePreviewWindow } from './WaysToUsePreviewWindow'

export function WebAppIllustration(): JSX.Element {
    return (
        <>
            <WaysToUsePreviewWindow title="Today">
                <div className="flex flex-col gap-2 p-3">
                    <Text size="xs" weight="semibold">
                        Good morning, Sam
                    </Text>
                    <div className="flex items-center gap-2">
                        <Dot variant="destructive" />
                        <Text size="xs">Errors doubled</Text>
                    </div>
                    <div className="flex items-center gap-2">
                        <Dot variant="success" />
                        <Text size="xs">Signups are up 12%</Text>
                    </div>
                </div>
            </WaysToUsePreviewWindow>
            <WaysToUsePreviewCallout>
                <div className="flex items-center gap-2">
                    <IconSparkles className="size-3.5 shrink-0 text-muted-foreground" />
                    <Text size="xs">Why the error spike?</Text>
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
                        <IconArrowRight className="size-3" />
                    </span>
                </div>
            </WaysToUsePreviewCallout>
        </>
    )
}
