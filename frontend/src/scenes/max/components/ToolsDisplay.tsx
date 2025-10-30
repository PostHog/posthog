import './QuestionInput.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { ReactNode, useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import React from 'react'

import { IconArrowRight, IconInfo, IconWrench, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { identifierToHuman } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { useResizeObserver } from '~/lib/hooks/useResizeObserver'

import {
    MAX_GENERALLY_CAN,
    MAX_GENERALLY_CANNOT,
    TOOL_DEFINITIONS,
    ToolDefinition,
    ToolRegistration,
    getToolDefinition,
} from '../max-constants'

export interface ToolsDisplayProps {
    isFloating?: boolean
    tools: ToolRegistration[]
    bottomActions?: ReactNode
    deepResearchMode?: boolean
}

export const ToolsDisplay: React.FC<ToolsDisplayProps> = ({ isFloating, tools, bottomActions, deepResearchMode }) => {
    // Tools not available in deep research mode
    if (deepResearchMode) {
        return <></>
    }
    // We show the tools reversed, so the ones registered last (scene-specific) are shown first
    const toolsInReverse = tools.toReversed()

    return (
        <div className="flex items-center w-full justify-center cursor-default">
            <Tooltip
                placement="bottom-end"
                fallbackPlacements={['left']}
                arrowOffset={
                    (placement) =>
                        placement.startsWith('bottom') ? 10 : 0 /* 10px from right edge to align with the info icon */
                }
                delayMs={50}
                title={<ToolsExplanation toolsInReverse={toolsInReverse} />}
            >
                <div
                    className={clsx(
                        'relative flex items-center text-xs font-medium justify-between gap-1 overflow-hidden',
                        !isFloating
                            ? 'w-[calc(100%-1rem)] px-1.5 pt-2 pb-1 -m-1 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                            : `w-full px-2 pb-1 pt-0.5`
                    )}
                >
                    <TruncatedHorizontalCollection>
                        <span className="shrink-0">Tools:</span>
                        {toolsInReverse.map((tool) => {
                            const toolDef = getToolDefinition(tool.identifier)
                            return (
                                // We're using --color-posthog-3000-300 instead of border-primary (--color-posthog-3000-200)
                                // or border-secondary (--color-posthog-3000-400) because the former is almost invisible here, and the latter too distinct
                                <em className="relative inline-flex items-center gap-1" key={tool.identifier}>
                                    <span className="flex text-sm">{toolDef?.icon || <IconWrench />}</span>
                                    {toolDef?.name}
                                </em>
                            )
                        })}
                    </TruncatedHorizontalCollection>
                    <IconInfo className="text-sm shrink-0 box-content z-10" />
                </div>
            </Tooltip>
            {bottomActions && <div className="ml-auto">{bottomActions}</div>}
        </div>
    )
}

/**
 * This component is used to truncate a horizontal collection of elements to its available width.
 * Shows a "+ n more" indicator when the collection overflows.
 * It's already abstracted out to a point where it can be easily used elswehere - just haven't put in the effort
 * to move it to the component library level.
 */
function TruncatedHorizontalCollection<Children extends React.ReactElement>({
    children,
}: {
    children: (Children | Children[])[]
}): JSX.Element {
    const childrenFlattened = children.flatMap((child) => child)

    /** Ref for the container of the collection */
    const containerRef = useRef<HTMLDivElement>(null)
    /** Ref for the elements in the variable-length collection */
    const collectionRef = useRef<HTMLElement[]>([])
    /** Ref for the element that shows "+ n more" */
    const overflowIndicatorRef = useRef<HTMLElement>(null)
    /** Number of elements that can currently be safely shown */
    const [visibleElementsCount, setVisibleElementsCount] = useState(0)

    const recalculateVisibleElementsCount = useCallback((): void => {
        let foundOverflow = false
        for (let i = 0; i < collectionRef.current.length; i++) {
            const toolEl = collectionRef.current[i]
            if (toolEl && containerRef.current) {
                const rightOverflow =
                    toolEl.getBoundingClientRect().right - containerRef.current.getBoundingClientRect().right
                // Items other than the last one need overflowIndicatorWidth px of space to the right to safely show "+ n more"
                const requiredSpacePx =
                    i === collectionRef.current.length - 1 ? 0 : overflowIndicatorRef.current?.clientWidth || 0
                if (rightOverflow > -requiredSpacePx) {
                    setVisibleElementsCount(i)
                    foundOverflow = true
                    break
                }
            }
        }
        if (!foundOverflow) {
            setVisibleElementsCount(collectionRef.current.length)
        }
    }, [childrenFlattened.length])

    // Force visibleElementsCount re-calc after first render and when the number of children changes
    useLayoutEffect(() => recalculateVisibleElementsCount(), [recalculateVisibleElementsCount])
    // Re-calc visibleElementsCount on container resize
    useResizeObserver({ ref: containerRef, onResize: recalculateVisibleElementsCount })

    return (
        <div className="flex items-center gap-1.5 min-w-0 flex-1" ref={containerRef}>
            {childrenFlattened
                .flatMap((child) => child)
                .map((child, index) => (
                    <span
                        key={index}
                        ref={(e) => e && (collectionRef.current[index] = e)}
                        className={clsx(
                            'flex relative flex-shrink-0',
                            index >= visibleElementsCount && '*:first:invisible'
                        )}
                    >
                        {React.cloneElement(child, {
                            ref: (e: HTMLElement) => e && (collectionRef.current[index] = e),
                        })}
                        {index === visibleElementsCount && (
                            <span
                                ref={overflowIndicatorRef}
                                className="absolute left-0 top-0 bottom-0 text-xs text-muted flex items-center"
                            >
                                + {childrenFlattened.length - visibleElementsCount} more
                            </span>
                        )}
                    </span>
                ))}
        </div>
    )
}

function ToolsExplanation({ toolsInReverse }: { toolsInReverse: ToolRegistration[] }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    /** Dynamic list of things Max can do right now, i.e. general capabilities + tools registered. */
    const maxCanHere = useMemo(
        () =>
            (toolsInReverse as { name?: string; description?: string; identifier?: keyof typeof TOOL_DEFINITIONS }[])
                .reduce(
                    (tools, tool) => {
                        const toolDef = tool.identifier ? TOOL_DEFINITIONS[tool.identifier] : undefined
                        if (toolDef?.subtools) {
                            tools.push(...Object.values(toolDef.subtools))
                        } else {
                            tools.push({ name: toolDef?.name, description: toolDef?.description, icon: toolDef?.icon })
                        }
                        return tools
                    },
                    [] as { name?: string; description?: string; icon?: JSX.Element }[]
                )
                .concat(MAX_GENERALLY_CAN)
                .map((tool) => (
                    <React.Fragment key={tool.name}>
                        <span className="flex text-base text-success shrink-0 ml-1 mr-2 h-[1.25em]">
                            {tool.icon || <IconWrench />}
                        </span>
                        <span>
                            <strong className="italic">{tool.name}</strong>
                            {tool.description?.replace(tool.name || '', '')}
                        </span>
                    </React.Fragment>
                )),
        [toolsInReverse.map((t) => t.name).join(';')] // eslint-disable-line react-hooks/exhaustive-deps
    )
    /** Dynamic list of things Max can do elsewhere in PostHog, by product. */
    const maxCanElsewhereByProduct = useMemo(
        () =>
            Object.entries(TOOL_DEFINITIONS)
                .filter(
                    ([_, tool]) =>
                        !toolsInReverse.find((registeredTool) => registeredTool.name === tool.name) &&
                        (!tool.flag || featureFlags[tool.flag])
                )
                .reduce(
                    (acc, [_, tool]) => {
                        if (!tool.product) {
                            return acc
                        }
                        if (!acc[tool.product]) {
                            acc[tool.product] = []
                        }
                        acc[tool.product]!.push(tool)
                        return acc
                    },
                    {} as Partial<Record<Scene, ToolDefinition[]>>
                ),
        [toolsInReverse.map((t) => t.name).join(';'), featureFlags] // eslint-disable-line react-hooks/exhaustive-deps
    )
    /** Dynamic list of things Max can do elsewhere in PostHog, by product. */
    const maxCanElsewhere = useMemo(
        () =>
            Object.entries(maxCanElsewhereByProduct).map(([product, tools]) => (
                <>
                    <IconArrowRight className="text-base text-secondary shrink-0 ml-1 mr-2 h-[1.25em]" />
                    <span>
                        <em>In {sceneConfigurations[product]?.name || identifierToHuman(product)}: </em>
                        {tools.map((tool, index) => (
                            <React.Fragment key={tool.name}>
                                <strong className="italic">{tool.name}</strong>
                                {tool.description?.replace(tool.name, '')}
                                {index < tools.length - 1 && <>; </>}
                            </React.Fragment>
                        ))}
                    </span>
                </>
            )),
        [maxCanElsewhereByProduct]
    )

    return (
        <>
            <div className="mb-2">
                <div className="font-semibold mb-0.5">Max can:</div>
                <ul className="space-y-0.5 text-sm *:flex *:items-start">
                    {maxCanHere.map((item, index) => (
                        <li key={`here-${index}`}>{item}</li>
                    ))}
                    {maxCanElsewhere.map((item, index) => (
                        <li key={`elsewhere-${index}`}>{item}</li>
                    ))}
                </ul>
            </div>
            <div>
                <div className="font-semibold mb-0.5">Max can't (yet):</div>
                <ul className="space-y-0.5 text-sm *:flex *:items-start">
                    {MAX_GENERALLY_CANNOT.map((item, index) => (
                        <li key={index}>
                            <IconX className="text-base text-danger shrink-0 ml-1 mr-2 h-[1.25em]" />
                            <span>{item}</span>
                        </li>
                    ))}
                </ul>
            </div>
        </>
    )
}
