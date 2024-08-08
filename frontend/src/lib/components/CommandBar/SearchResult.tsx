import { LemonSkeleton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import { useLayoutEffect, useRef } from 'react'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { JSONContent } from 'scenes/notebooks/Notebook/utils'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'

import { getQueryFromInsightLike } from '~/queries/nodes/InsightViz/utils'

import { tabToName } from './constants'
import { searchBarLogic } from './searchBarLogic'
import { SearchResult as ResultType } from './types'

type SearchResultProps = {
    result: ResultType
    resultIndex: number
    focused: boolean
}

export const SearchResult = ({ result, resultIndex, focused }: SearchResultProps): JSX.Element => {
    const { aggregationLabel } = useValues(searchBarLogic)
    const { openResult } = useActions(searchBarLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    useLayoutEffect(() => {
        if (focused) {
            // :HACKY: This uses the non-standard scrollIntoViewIfNeeded api
            // to improve scroll behaviour. Change to scrollIntoView({ scrollMode: 'if-needed' })
            // once available.
            if ((ref.current as any)?.scrollIntoViewIfNeeded) {
                ;(ref.current as any).scrollIntoViewIfNeeded(false)
            } else {
                ref.current?.scrollIntoView()
            }
        }
    }, [focused])

    return (
        <div
            className={clsx(
                'w-full px-2 hover:bg-bg-3000 border-l-4 border-r border-b cursor-pointer',
                focused ? 'bg-bg-3000 border-l-primary-3000' : 'bg-bg-light'
            )}
            onClick={() => {
                openResult(resultIndex)
            }}
            ref={ref}
        >
            <div className="px-2 py-3 w-full space-y-0.5 flex flex-col items-start">
                <span className="text-muted-3000 text-xs">
                    {result.type !== 'group'
                        ? tabToName[result.type]
                        : `${capitalizeFirstLetter(aggregationLabel(result.extra_fields.group_type_index).plural)}`}
                </span>
                <span className="text-text-3000 font-bold">
                    <ResultName result={result} />
                </span>
            </div>
        </div>
    )
}

export const SearchResultSkeleton = (): JSX.Element => (
    <div className="px-5 py-4 w-full space-y-1.5 flex flex-col items-start bg-bg-light border-b">
        <LemonSkeleton className="w-16 opacity-75 h-3" />
        <LemonSkeleton className="w-40 h-3.5" />
    </div>
)

type ResultNameProps = {
    result: ResultType
}

export const ResultName = ({ result }: ResultNameProps): JSX.Element | null => {
    const summarizeInsight = useSummarizeInsight()

    const { type, extra_fields } = result
    if (type === 'insight') {
        const query = getQueryFromInsightLike(extra_fields)
        return extra_fields.name ? <span>{extra_fields.name}</span> : <i>{summarizeInsight(query)}</i>
    } else if (type === 'feature_flag') {
        return <span>{extra_fields.key}</span>
    } else if (type === 'notebook') {
        return <span>{extra_fields.title}</span>
    } else if (type === 'group') {
        return <span>{groupDisplayId(extra_fields.group_key, extra_fields.group_properties)}</span>
    }
    return <span>{extra_fields.name}</span>
}

export const ResultDescription = ({ result }: ResultNameProps): JSX.Element | null => {
    const { result_id, type, extra_fields } = result
    if (type === 'feature_flag') {
        return extra_fields.name && extra_fields.name !== extra_fields.key ? (
            <span>{extra_fields.name}</span>
        ) : (
            <i>No description.</i>
        )
    } else if (type === 'notebook') {
        return (
            <Notebook
                shortId={result_id}
                mode="notebook"
                editable={false}
                initialContent={extra_fields.content as JSONContent}
            />
        )
    }
    return 'description' in extra_fields ? <span>{extra_fields.description}</span> : <i>No description.</i>
}
