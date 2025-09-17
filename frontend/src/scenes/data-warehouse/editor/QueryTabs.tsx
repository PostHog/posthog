import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { NEW_QUERY, QueryTab, multitabEditorLogic } from './multitabEditorLogic'

interface QueryTabsProps {
    models: QueryTab[]
    activeTab: QueryTab | null
}

export function QueryTabs({ models, activeTab }: QueryTabsProps): JSX.Element {
    const { allTabs } = useValues(multitabEditorLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const prevTabsCountRef = useRef(allTabs.length)

    useEffect(() => {
        if (allTabs.length > prevTabsCountRef.current) {
            containerRef.current?.scrollTo({
                left: containerRef.current.scrollWidth,
                behavior: 'smooth',
            })
        }

        prevTabsCountRef.current = allTabs.length
    }, [allTabs])

    return (
        <>
            <div
                // height is hardcoded to match implicit height from tree view nav bar
                className="flex flex-row overflow-auto hide-scrollbar h-[39px]"
                ref={containerRef}
            >
                {models.map((model: QueryTab) => (
                    <QueryTabComponent
                        key={model.uri.path}
                        model={model}
                        active={activeTab?.uri.path === model.uri.path}
                    />
                ))}
            </div>
        </>
    )
}

interface QueryTabProps {
    model: QueryTab
    active: boolean
}

function QueryTabComponent({ model, active }: QueryTabProps): JSX.Element {
    const [tabName, setTabName] = useState(() => model.name || NEW_QUERY)
    const [isEditing, setIsEditing] = useState(false)

    useEffect(() => {
        setTabName(model.name || model.view?.name || NEW_QUERY)
    }, [model.view?.name, model.name])

    return (
        <div
            className={clsx(
                'deprecated-space-y-px p-1 flex border-b-2 flex-row items-center gap-1 hover:bg-surface-primary cursor-pointer',
                active
                    ? 'bg-surface-primary border-b-2 !border-brand-yellow'
                    : 'bg-surface-secondary border-transparent',
                'px-3'
            )}
        >
            <div
                onDoubleClick={() => {
                    // disable editing views
                    if (model.view) {
                        return
                    }
                    setIsEditing(!isEditing)
                }}
                className="flex-grow text-left whitespace-pre"
            >
                {tabName}
            </div>
        </div>
    )
}
