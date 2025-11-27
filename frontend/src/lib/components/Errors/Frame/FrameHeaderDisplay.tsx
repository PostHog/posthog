import { useValues } from 'kea'

import { IconBox, IconCircleDashed } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { cancelEvent } from 'products/error_tracking/frontend/utils'

import { FingerprintRecordPartDisplay } from '../FingerprintRecordPartDisplay'
import { GitProviderFileLink } from '../GitProviderFileLink'
import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { framesCodeSourceLogic } from '../framesCodeSourceLogic'
import { ErrorTrackingStackFrame } from '../types'
import { formatResolvedName } from '../utils'

export function FrameHeaderDisplay({ frame }: { frame: ErrorTrackingStackFrame }): JSX.Element {
    const { raw_id, source, line, column, resolved, resolve_failure, in_app } = frame
    const { getFrameFingerprint } = useValues(errorPropertiesLogic)
    const { getSourceDataForFrame } = useValues(framesCodeSourceLogic)

    const part = getFrameFingerprint(raw_id)
    const resolvedName = formatResolvedName(frame)
    const sourceData = getSourceDataForFrame(raw_id)

    return (
        <div className="flex flex-1 justify-between items-center h-full">
            <div className="flex flex-wrap gap-x-1">
                {resolvedName ? (
                    <div className="flex">
                        <span>{resolvedName}</span>
                    </div>
                ) : null}
                <div className="flex font-light text-xs">
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
                {in_app && sourceData?.url && <GitProviderFileLink sourceData={sourceData} />}
                {resolved && source && (
                    <span onClick={cancelEvent} className="text-secondary">
                        <CopyToClipboardInline
                            tooltipMessage="Copy file name"
                            iconSize="xsmall"
                            explicitValue={source}
                            iconMargin={false}
                        />
                    </span>
                )}
                {part && <FingerprintRecordPartDisplay part={part} />}
                {!in_app && (
                    <Tooltip title="Vendor frame">
                        <IconBox className="mr-0.5 text-secondary" fontSize={15} />
                    </Tooltip>
                )}
                {in_app && !resolved && (
                    <Tooltip title={resolve_failure}>
                        <IconCircleDashed className="mr-0.5 text-secondary" fontSize={15} />
                    </Tooltip>
                )}
            </div>
        </div>
    )
}
