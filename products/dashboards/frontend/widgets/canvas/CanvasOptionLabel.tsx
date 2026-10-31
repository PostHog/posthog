import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { fullName } from 'lib/utils/strings'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

export function CanvasOptionLabel({ canvas }: { canvas: CanvasApi }): JSX.Element {
    const creator = canvas.created_by
    const creatorName = creator ? fullName(creator) || creator.email : null
    return (
        <span className="flex w-full items-center justify-between gap-2">
            <span className="min-w-0 flex-1 truncate">{canvas.name}</span>
            {creator ? (
                <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted">
                    <ProfilePicture
                        user={{ first_name: creator.first_name, last_name: creator.last_name, email: creator.email }}
                        size="sm"
                    />
                    <span className="max-w-32 truncate">{creatorName}</span>
                </span>
            ) : null}
        </span>
    )
}
