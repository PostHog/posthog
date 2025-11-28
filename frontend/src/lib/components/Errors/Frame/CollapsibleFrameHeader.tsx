import { CollapsibleTrigger } from '@radix-ui/react-collapsible'
import { useValues } from 'kea'

import { IconBox, IconCircleDashed, IconEllipsis } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { FingerprintRecordPartDisplay } from '../FingerprintRecordPartDisplay'
import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { formatResolvedName } from '../utils'
import { FrameDropDownMenu } from './FrameDropDownMenu'

export function CollapsibleFrameHeader({
    frame,
    record,
}: {
    frame: ErrorTrackingStackFrame
    record: ErrorTrackingStackFrameRecord
    expanded: boolean
}): JSX.Element {
    const { raw_id, source, line, column, resolved, resolve_failure, in_app } = frame
    const { getFrameFingerprint } = useValues(errorPropertiesLogic)

    const part = getFrameFingerprint(raw_id)
    const resolvedName = formatResolvedName(frame)

    return (
        <div className={cn('flex justify-between items-center w-full h-7')}>
            <CollapsibleTrigger asChild>
                <ButtonPrimitive className="flex justify-between items-center rounded-none w-full h-full">
                    <div className="flex flex-wrap gap-x-1 items-center text-xs">
                        {resolvedName ? <span>{resolvedName}</span> : null}
                        <div className="flex font-light">
                            <span>{source}</span>
                            {line ? (
                                <>
                                    <span className="text-secondary">@</span>
                                    <span>
                                        {line}
                                        {column && `:${column}`}
                                    </span>
                                </>
                            ) : null}
                        </div>
                    </div>
                    <div className="flex gap-x-1 items-center justify-end">
                        {part && <FingerprintRecordPartDisplay part={part} />}
                        {!in_app && (
                            <Tooltip title="Vendor frame">
                                <IconBox className="text-secondary" fontSize={15} />
                            </Tooltip>
                        )}
                        {in_app && !resolved && (
                            <Tooltip title={resolve_failure}>
                                <IconCircleDashed className="text-secondary" fontSize={15} />
                            </Tooltip>
                        )}
                    </div>
                </ButtonPrimitive>
            </CollapsibleTrigger>
            <div className="border-r-1 w-0 h-full" />
            <FrameDropDownMenu className="h-full w-7 rounded-none outline-none" frame={frame} record={record}>
                <IconEllipsis />
            </FrameDropDownMenu>
        </div>
    )
}
