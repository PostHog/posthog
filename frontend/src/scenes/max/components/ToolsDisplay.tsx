import { IconX, IconWrench, IconInfo, IconArrowRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { ReactNode, useState, useRef, useEffect, useCallback, useMemo } from 'react'
import React from 'react'

import { useResizeObserver } from '~/lib/hooks/useResizeObserver'

import {
    ToolDefinition,
    TOOL_DEFINITIONS,
    ToolRegistration,
    MAX_GENERALLY_CAN,
    MAX_GENERALLY_CANNOT,
} from '../max-constants'
import { AssistantContextualTool } from '~/queries/schema/schema-assistant-messages'
import { identifierToHuman } from 'lib/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import './QuestionInput.scss'

/** Roughly how much the "+ n more" span takes up. */
const PLUS_N_MORE_SPAN_WIDTH_PX = 56

export interface ToolsDisplayProps {
    isFloating?: boolean
    tools: ToolRegistration[]
    bottomActions?: ReactNode
}

export const ToolsDisplay: React.FC<ToolsDisplayProps> = ({ isFloating, tools, bottomActions }) => {
    const toolsContainerRef = useRef<HTMLDivElement>(null)
    const toolsRef = useRef<HTMLElement[]>([])
    const [firstToolOverflowing, setFirstToolOverflowing] = useState<AssistantContextualTool | null>(null)

    const onResize = useCallback((): void => {
        let foundOverflow = false
        for (let i = 0; i < toolsRef.current.length; i++) {
            const toolEl = toolsRef.current[i]
            if (toolEl) {
                const rightOverflow =
                    toolEl.getBoundingClientRect().right - toolEl.parentElement!.getBoundingClientRect().right
                // Items other than the last one need PLUS_N_MORE_SPAN_WIDTH_PX of space to the right to safely show "+ n more"
                const freeSpaceRequirementPx = i < toolsRef.current.length - 1 ? PLUS_N_MORE_SPAN_WIDTH_PX : 0
                if (rightOverflow > -freeSpaceRequirementPx) {
                    setFirstToolOverflowing(tools[tools.length - i - 1].identifier)
                    foundOverflow = true
                    break
                }
            }
        }
        if (!foundOverflow) {
            setFirstToolOverflowing(null)
        }
    }, [tools.map((t) => t.name).join(';')]) // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => onResize(), [onResize])
    useResizeObserver({ ref: toolsContainerRef, onResize })

    // We show the tools reversed, so the ones registered last (scene-specific) are shown first
    const toolsInReverse = tools.toReversed()
    const toolsHidden = firstToolOverflowing
        ? toolsInReverse
              .slice(toolsInReverse.findIndex((tool) => tool.identifier === firstToolOverflowing))
              .map((tool) => tool.identifier)
        : []

    return (
        <div ref={toolsContainerRef} className="flex items-center w-full justify-center cursor-default">
            <Tooltip
                placement="bottom-end"
                arrowOffset={6 /* 6px from right edge to align with the info icon */}
                delayMs={50}
                title={<ToolsExplanation toolsInReverse={toolsInReverse} />}
            >
                <div
                    className={clsx(
                        'relative flex items-center text-xs font-medium justify-between gap-1 pl-1 overflow-hidden',
                        !isFloating
                            ? 'w-[calc(100%-1rem)] py-0.75 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                            : `w-full pb-1`
                    )}
                >
                    <div className="flex items-center gap-1.5">
                        <span className="shrink-0">Tools:</span>
                        {toolsInReverse.map((tool, index) => (
                            <span
                                key={tool.identifier}
                                ref={(e) => e && (toolsRef.current[index] = e)}
                                className={clsx(
                                    'relative flex-shrink-0',
                                    index === toolsInReverse.length - 1 && 'grow'
                                )}
                            >
                                {/* We're using --color-posthog-3000-300 instead of border-primary (--color-posthog-3000-200)
                                or border-secondary (--color-posthog-3000-400) because the former is almost invisible here, and the latter too distinct */}
                                <ToolPill tool={tool} hidden={toolsHidden.includes(tool.identifier)} />
                                {tool.identifier === firstToolOverflowing && (
                                    <span className="absolute left-0 top-0 bottom-0 text-xs text-muted flex items-center">
                                        + {toolsHidden.length} more
                                    </span>
                                )}
                            </span>
                        ))}
                    </div>
                    <IconInfo className="text-sm p-1 shrink-0 box-content z-10" />
                </div>
            </Tooltip>
            {bottomActions && <div className="ml-auto">{bottomActions}</div>}
        </div>
    )
}

function ToolPill({ tool, hidden }: { tool: ToolRegistration; hidden?: boolean }): JSX.Element {
    return (
        <em className={clsx('relative inline-flex items-center gap-1', hidden && 'invisible')}>
            <span className="text-sm">{tool.icon || <IconWrench />}</span>
            {tool.name}
        </em>
    )
}

function ToolsExplanation({ toolsInReverse }: { toolsInReverse: ToolRegistration[] }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    /** Dynamic list of things Max can do right now, i.e. general capabilities + tools registered. */
    const maxCanHere = useMemo(
        () =>
            (toolsInReverse as { icon?: JSX.Element; name?: string; description?: string }[])
                .concat(MAX_GENERALLY_CAN)
                .map((tool) => (
                    <>
                        <span className="flex text-base text-success shrink-0 ml-1 mr-2 h-[1.25em]">
                            {tool.icon || <IconWrench />}
                        </span>
                        <span>
                            <strong className="italic">{tool.name}</strong>
                            {tool.description?.replace(tool.name || '', '')}
                        </span>
                    </>
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
                            console.warn(`Unexpected: Global Max tool ${tool.name} appears not to be registered`)
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
                            <React.Fragment key={index}>
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
