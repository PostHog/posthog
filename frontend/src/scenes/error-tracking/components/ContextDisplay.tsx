import { IconCopy } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import useIsHovering from 'lib/hooks/useIsHovering'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { cancelEvent } from '../utils'

export function ContextDisplay({ className }: { className?: string }): JSX.Element {
    const { exceptionAttributes, showContext, propertiesLoading } = useValues(errorTrackingIssueSceneLogic)
    return (
        <div className={cn('pt-14 transition-[width] duration-200', className)}>
            {match([showContext, propertiesLoading, exceptionAttributes])
                .with([false, P.any, P.any], () => null)
                .with([true, true, P.any], () => (
                    <div className="flex justify-center w-full h-32 items-center">
                        <Spinner />
                    </div>
                ))
                .with([true, false, P.nullish], () => <div>No data available</div>)
                .with([true, false, P.any], ([, , attrs]) => {
                    return (
                        <table
                            className="border-spacing-0 border-separate rounded w-full border overflow-hidden cursor-default"
                            onClick={cancelEvent}
                        >
                            <tbody className="w-full">
                                {[
                                    { label: 'Level', value: attrs?.level },
                                    { label: 'Synthetic', value: attrs?.synthetic },
                                    { label: 'Library', value: attrs?.library },
                                    { label: 'Unhandled', value: attrs?.unhandled },
                                    { label: 'Browser', value: attrs?.browser },
                                    { label: 'OS', value: attrs?.os },
                                    { label: 'URL', value: attrs?.url },
                                ]
                                    .filter((row) => row.value !== undefined)
                                    .map((row, index) => (
                                        <ContextRow key={index} label={row.label} value={String(row.value)} />
                                    ))}
                            </tbody>
                        </table>
                    )
                })
                .exhaustive()}
        </div>
    )
}

type ContextRowProps = {
    label: string
    value: string
}

function ContextRow({ label, value }: ContextRowProps): JSX.Element {
    const valueRef = useRef<HTMLTableCellElement>(null)
    const isHovering = useIsHovering(valueRef)
    return (
        <tr className="even:bg-fill-tertiary w-full">
            <th className="border-r-1 font-semibold text-xs p-1 w-1/3 text-left">{label}</th>
            <td ref={valueRef} className="w-full truncate p-1 text-xs max-w-0 relative" title={value}>
                {String(value)}
                <div className="absolute right-0 top-[50%] translate-y-[-50%]" hidden={!isHovering}>
                    <LemonButton
                        size="xsmall"
                        className="p-0 rounded-none"
                        tooltip="Copy"
                        onClick={() => {
                            copyToClipboard(value).catch((error) => {
                                console.error('Failed to copy to clipboard:', error)
                            })
                        }}
                    >
                        <IconCopy />
                    </LemonButton>
                </div>
            </td>
        </tr>
    )
}
