import clsx from 'clsx'

import { Lettermark } from '../Lettermark'

export interface UploadedLogoProps {
    name: string
    mediaId?: string | null
    /** @default 'medium' */
    size?: 'xsmall' | 'medium' | 'xlarge'
}

export function UploadedLogo({ name, mediaId, size = 'medium' }: UploadedLogoProps): JSX.Element {
    if (!mediaId) {
        return <Lettermark name={name} size={size} />
    }

    return (
        <div
            className={clsx(
                'relative flex overflow-hidden select-none',
                size === 'xlarge'
                    ? 'size-16 rounded before:absolute before:inset-0 before:border before:rounded'
                    : size === 'medium'
                    ? 'size-6 rounded-sm'
                    : 'size-4 rounded-sm'
            )}
        >
            <img
                className="size-full object-cover"
                src={mediaId.startsWith('data:') ? mediaId : `/uploaded_media/${mediaId}`}
            />
        </div>
    )
}
