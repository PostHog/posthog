import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { cn } from 'lib/utils/css-classes'

export interface ProjectLogoProps {
    name: string
    projectId: number
    mediaId?: string | null
    size: 'xsmall' | 'small'
}

export function ProjectLogo({ name, projectId, mediaId, size }: ProjectLogoProps): JSX.Element {
    if (mediaId) {
        return <UploadedLogo name={name} entityId={projectId} mediaId={mediaId} size={size} />
    }

    return (
        <div
            className={cn(
                'Lettermark bg-[var(--color-bg-fill-button-tertiary-active)] dark:text-tertiary',
                size === 'xsmall' ? 'size-4 text-[8px]' : 'size-5'
            )}
        >
            {String.fromCodePoint(name.codePointAt(0)!).toLocaleUpperCase()}
        </div>
    )
}
