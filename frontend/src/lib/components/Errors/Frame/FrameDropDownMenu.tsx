import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconCopy, IconExternal, IconGitLab, IconGithub } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
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
    const { sourceLinkReleaseId } = useValues(errorPropertiesLogic)
    const { getSourceDataForFrame } = useValues(framesCodeSourceLogic)
    const sourceData = getSourceDataForFrame(raw_id, sourceLinkReleaseId)
    const lineLocation = getLineLocation(frame)
    const hasItems = !!(frame.resolved_name || frame.source || lineLocation || sourceData)
    const [open, setOpen] = useState(false)

    if (!hasItems) {
        return (
            <ButtonPrimitive className={className} disabled>
                {children}
            </ButtonPrimitive>
        )
    }

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive className={className}>{children}</ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="p-1">
                {frame.resolved_name && <CopyItem value={frame.resolved_name} description="function name" />}
                {frame.source && <CopyItem value={frame.source} description="file path" />}
                {lineLocation && <CopyItem value={lineLocation} description="line location" />}
                {sourceData && <DropdownMenuSeparator />}
                {sourceData && <SourceDataLink sourceData={sourceData} onClick={() => setOpen(false)} />}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

const PROVIDER_ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
    github: IconGithub,
    gitlab: IconGitLab,
}

const PROVIDER_NAME_MAP: Record<string, string> = {
    github: 'GitHub',
    gitlab: 'GitLab',
}

export function SourceDataLink({ sourceData, onClick }: { sourceData: SourceData; onClick?: () => void }): JSX.Element {
    const ProviderIcon = sourceData.provider ? PROVIDER_ICON_MAP[sourceData.provider] : null
    const Icon = ProviderIcon || IconExternal
    // Not a Radix menu item, like the copy items next to it. Radix focuses an item on hover, and a
    // focused link gets the global focus outline, which its sibling buttons never show on hover.
    return (
        <LinkPrimitive
            to={sourceData.url}
            target="_blank"
            className={buttonPrimitiveVariants({ menuItem: true })}
            onClick={() => {
                posthog.capture('error_tracking_source_link_clicked', { provider: sourceData.provider })
                onClick?.()
            }}
        >
            <Icon />
            Open in {PROVIDER_NAME_MAP[sourceData.provider] ?? sourceData.provider}
        </LinkPrimitive>
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
