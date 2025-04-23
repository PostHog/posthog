import { LemonTable, Spinner } from '@posthog/lemon-ui'
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
                    const dataSource = [
                        { property: 'Level', value: attrs?.level },
                        { property: 'Synthetic', value: attrs?.synthetic },
                        { property: 'Library', value: attrs?.library },
                        { property: 'Unhandled', value: attrs?.unhandled },
                        { property: 'Browser', value: attrs?.browser },
                        { property: 'OS', value: attrs?.os },
                        { property: 'URL', value: attrs?.url },
                    ].filter((row) => row.value !== undefined)

                    return (
                        <LemonTable
                            size="small"
                            firstColumnSticky
                            showHeader={false}
                            columns={[
                                {
                                    title: 'Property',
                                    dataIndex: 'property',
                                    className: 'font-semibold',
                                },
                                {
                                    title: 'Value',
                                    dataIndex: 'value',
                                    className: 'truncate',
                                    render: (dataValue) => String(dataValue),
                                },
                            ]}
                            dataSource={dataSource}
                        />
                    )
                })
                .exhaustive()}
        </div>
    )
}
