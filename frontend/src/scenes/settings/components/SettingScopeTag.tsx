import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import { Badge, Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

export type SettingScope = 'user' | 'project'

const SCOPE_COPY: Record<SettingScope, { label: string; tooltip: string }> = {
    user: { label: 'Only you', tooltip: 'This setting changes only your own agent runs.' },
    project: {
        label: 'Everyone in this project',
        tooltip: 'This setting changes agent runs for everyone in this project.',
    },
}

export function SettingScopeTag({ scope }: { scope: SettingScope }): JSX.Element {
    const quillSurface = useQuillSurface()
    const { label, tooltip } = SCOPE_COPY[scope]

    if (quillSurface) {
        return (
            <QuillTooltip>
                <TooltipTrigger
                    render={
                        <Badge
                            variant={scope === 'project' ? 'warning' : 'default'}
                            className="ml-2 align-middle"
                            tabIndex={0}
                        />
                    }
                >
                    {label}
                </TooltipTrigger>
                <TooltipContent>{tooltip}</TooltipContent>
            </QuillTooltip>
        )
    }

    return (
        <Tooltip title={tooltip}>
            <LemonTag size="small" type={scope === 'project' ? 'warning' : 'muted'} className="ml-2 align-middle">
                {label}
            </LemonTag>
        </Tooltip>
    )
}
