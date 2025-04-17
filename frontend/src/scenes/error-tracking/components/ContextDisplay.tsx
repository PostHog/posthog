import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
export function ContextDisplay(): JSX.Element {
    const { exceptionAttributes, propertiesLoading } = useValues(errorTrackingIssueSceneLogic)
    return (
        <div>
            {match([propertiesLoading, exceptionAttributes])
                .with([true, P.any], () => (
                    <div className="flex justify-center w-full h-32 items-center">
                        <Spinner />
                    </div>
                ))
                .with([false, P.nullish], () => <div>No data available</div>)
                .with([false, P.any], ([_, attrs]) => {
                    return (
                        <table className="w-full overflow-hidden">
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
