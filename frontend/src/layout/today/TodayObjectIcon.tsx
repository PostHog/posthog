import { IconStack, IconStackItem } from '@posthog/quill'

import { getIconColor, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

export function TodayObjectIcon({ type, className }: { type: string | undefined; className: string }): JSX.Element {
    const [color] = getIconColor(type)
    return (
        <IconStack className={className}>
            <IconStackItem color={color === 'currentColor' ? undefined : color}>
                {iconForType(type as FileSystemIconType | undefined)}
            </IconStackItem>
        </IconStack>
    )
}
