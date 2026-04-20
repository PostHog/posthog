import { useValues } from 'kea'

import { IconCopy, IconExternal, IconGitLab, IconGithub } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { SourceData, framesCodeSourceLogic } from './framesCodeSourceLogic'

export function FrameDropDownMenu({
    frame,
    children,
    className,
}: {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord
    children: React.ReactNode
    className?: string
}): JSX.Element {
    const { raw_id } = frame
    const { getSourceDataForFrame } = useValues(framesCodeSourceLogic)
    const sourceData = getSourceDataForFrame(raw_id)
    const lineLocation = getLineLocation(frame)
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive className={className}>{children}</ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="p-1">
                {frame.resolved_name && <CopyItem value={frame.resolved_name} description="function name" />}
                {frame.source && <CopyItem value={frame.source} description="file path" />}
                {lineLocation && <CopyItem value={lineLocation} description="line location" />}
                {sourceData && <DropdownMenuSeparator />}
                {sourceData && <SourceDataLink sourceData={sourceData} />}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

const PROVIDER_ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
    github: IconGithub,
    gitlab: IconGitLab,
}

export function SourceDataLink({ sourceData }: { sourceData: SourceData }): JSX.Element {
    const ProviderIcon = sourceData.provider ? PROVIDER_ICON_MAP[sourceData.provider] : null
    const Icon = ProviderIcon || IconExternal
    return (
        <DropdownMenuItem>
            <Link to={sourceData.url} target="_blank" className="inline-flex items-center">
                <Icon className="w-3.5 h-3.5" />
                Open in {sourceData.provider}
            </Link>
        </DropdownMenuItem>
    )
}

export function CopyItem({ value, description }: { value: string; description: string }): JSX.Element {
    return (
        <ButtonPrimitive menuItem onClick={() => copyToClipboard(value, description)}>
            <IconCopy />
            Copy {description}
        </ButtonPrimitive>
    )
}

function getLineLocation(frame: ErrorTrackingStackFrame): string | null {
    if (!frame.source || !frame.line) {
        return null
    }
    return `${frame.source}:${frame.line}`
}
