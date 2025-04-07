import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
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
                        <table className="border-spacing-0 border-separate rounded w-full border overflow-hidden">
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
                                        <tr key={index} className="even:bg-fill-tertiary w-full">
                                            <th className="border-r-1 font-semibold text-xs p-1 w-1/3 text-left">
                                                {row.label}
                                            </th>
                                            <td
                                                className="w-full truncate p-1 text-xs max-w-0"
                                                title={String(row.value)}
                                            >
                                                {String(row.value)}
                                            </td>
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                    )
                })
                .exhaustive()}
        </div>
    )
}
