import { LemonTag } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill'

import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

export type SettingStatus = 'experimental' | 'beta'

export function SettingStatusTag({ status }: { status: SettingStatus }): JSX.Element {
    const quillSurface = useQuillSurface()

    if (quillSurface) {
        return (
            <Badge variant={status === 'experimental' ? 'warning' : 'info'} className="ml-2 align-middle">
                {status === 'experimental' ? 'Experimental' : 'Beta'}
            </Badge>
        )
    }

    return status === 'experimental' ? (
        <LemonTag type="warning" className="ml-1 uppercase">
            Experimental
        </LemonTag>
    ) : (
        <LemonTag type="highlight" size="small" className="ml-1">
            Beta
        </LemonTag>
    )
}
