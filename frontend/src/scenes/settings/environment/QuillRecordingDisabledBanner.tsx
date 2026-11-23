import { Item, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillRecordingDisabledBanner(): JSX.Element {
    return (
        <Item tone="warning" size="sm">
            <ItemContent>
                <ItemDescription>
                    <strong>Recording is disabled.</strong> Enable it in General settings.
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
