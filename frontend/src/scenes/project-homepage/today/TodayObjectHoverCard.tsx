import { Item, ItemContent, ItemTitle } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { TodayHoverCardFact } from '~/layout/today/TodayHoverCardFact'
import type { TodayObjectPreview } from '~/layout/today/todayPreviewCards'
import { activityDetail } from '~/layout/today/todayWorkItems'
import { FileSystemIconType } from '~/queries/schema/schema-general'

export function TodayObjectHoverCard({ preview }: { preview: TodayObjectPreview }): JSX.Element {
    const viewed = activityDetail(preview.lastViewedAt)
    const created = activityDetail(preview.createdAt)
    return (
        <div className="flex flex-col" data-attr="today-object-hover-card">
            <Item size="xs" className="items-start">
                <ItemContent className="min-w-0 gap-2">
                    <ItemTitle className="flex items-start gap-2 wrap-anywhere">
                        <span className="group/colorful-product-icons colorful-product-icons-true flex h-lh w-4 shrink-0 items-center justify-center">
                            {iconForType((preview.type ?? undefined) as FileSystemIconType | undefined)}
                        </span>
                        <span className="min-w-0 font-semibold">{preview.name}</span>
                    </ItemTitle>
                    <div className="flex flex-col gap-1 pl-6">
                        {preview.typeName && (
                            <TodayHoverCardFact label="Type">
                                {preview.typeName.charAt(0).toUpperCase() + preview.typeName.slice(1)}
                            </TodayHoverCardFact>
                        )}
                        {preview.folder && <TodayHoverCardFact label="Folder">{preview.folder}</TodayHoverCardFact>}
                        {viewed && (
                            <TodayHoverCardFact label="Viewed">
                                <span title={viewed.title}>{viewed.text}</span>
                            </TodayHoverCardFact>
                        )}
                        {created && (
                            <TodayHoverCardFact label="Created">
                                <span title={created.title}>{created.text}</span>
                            </TodayHoverCardFact>
                        )}
                    </div>
                </ItemContent>
            </Item>
        </div>
    )
}
