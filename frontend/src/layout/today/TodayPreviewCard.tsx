import { PreviewCard } from '@base-ui/react/preview-card'

import { Card } from '@posthog/quill'

import { todayPreviewCardHandle } from './todayPreviewCardHandle'
import { TodaySessionPreview } from './TodaySessionPreview'
import { TodaySpacePreview } from './TodaySpacePreview'

/** The one hover card that every rail row with a `preview` opens. Mount it once, next to the rows. */
export function TodayPreviewCard(): JSX.Element {
    return (
        <PreviewCard.Root handle={todayPreviewCardHandle}>
            {({ payload }) =>
                payload ? (
                    <PreviewCard.Portal>
                        <PreviewCard.Positioner side="right" align="center" sideOffset={8} className="z-50">
                            <PreviewCard.Popup
                                data-attr="today-preview-card"
                                render={
                                    <Card size="sm" className="w-72 gap-2 border border-border px-3 py-2.5 shadow-md" />
                                }
                            >
                                {payload.kind === 'session' ? (
                                    <TodaySessionPreview key={`session-${payload.item.id}`} item={payload.item} />
                                ) : (
                                    <TodaySpacePreview key={`space-${payload.space.id}`} space={payload.space} />
                                )}
                            </PreviewCard.Popup>
                        </PreviewCard.Positioner>
                    </PreviewCard.Portal>
                ) : null
            }
        </PreviewCard.Root>
    )
}
