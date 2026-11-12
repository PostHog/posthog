import { IconExternal } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function QuillQueryDebuggerButton({ query }: { query: Record<string, any> }): JSX.Element {
    return (
        <Button
            variant="outline"
            render={<LinkPrimitive to={urls.debugQuery(query)} target="_blank" />}
            data-attr="insight-error-query"
        >
            Open in query debugger
            <IconExternal />
        </Button>
    )
}
