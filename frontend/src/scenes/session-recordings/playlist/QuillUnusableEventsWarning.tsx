import { Button } from '@posthog/quill'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillListNotice } from './QuillListNotice'

export function QuillUnusableEventsWarning({
    unusableEventsInFilter,
}: {
    unusableEventsInFilter: string[]
}): JSX.Element {
    return (
        <QuillListNotice tone="warning">
            <p>Cannot use these events to filter for session recordings:</p>
            <p className="my-1">
                {unusableEventsInFilter.map((event) => (
                    <span key={event}>"{event}"</span>
                ))}
            </p>
            <p>
                Events have to have a <PropertyKeyInfo value="$session_id" /> to be used to filter recordings. This is
                added automatically by{' '}
                <Button
                    variant="link"
                    size="inline"
                    render={<LinkPrimitive to="https://posthog.com/docs/libraries/js" target="_blank" />}
                >
                    the Web SDK
                </Button>
                ,{' '}
                <Button
                    variant="link"
                    size="inline"
                    render={<LinkPrimitive to="https://posthog.com/docs/libraries" target="_blank" />}
                >
                    and the Mobile SDKs (Android, iOS, React Native and Flutter)
                </Button>
            </p>
        </QuillListNotice>
    )
}
