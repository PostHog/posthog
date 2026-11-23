import { Item, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillAnyWith100SamplingWarning({ isV2TriggersEnabled }: { isV2TriggersEnabled: boolean }): JSX.Element {
    return (
        <Item tone="destructive" size="sm">
            <ItemContent>
                <ItemDescription>
                    <strong>100% sampling rate with "any" matching records every session.</strong> To fix this, either
                    lower the sample rate or switch to "all" matching.
                    {isV2TriggersEnabled && (
                        <>
                            {' '}
                            Consider using <strong>trigger groups</strong> above for more precise control over when
                            sessions are recorded.
                        </>
                    )}
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
