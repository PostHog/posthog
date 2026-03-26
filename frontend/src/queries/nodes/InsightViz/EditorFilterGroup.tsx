import clsx from 'clsx'
import posthog from 'posthog-js'
import { Fragment, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { inStorybook, inStorybookTestRunner, slugify } from 'lib/utils'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import type { InsightEditorFilterGroup, InsightLogicProps } from '~/types'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insightProps: InsightLogicProps
    query: InsightQueryNode
    asTile?: boolean
}

export function EditorFilterGroup({ insightProps, editorFilterGroup, asTile }: EditorFilterGroupProps): JSX.Element {
    const { title, defaultExpanded, editorFilters, collapsedSummary } = editorFilterGroup
    const hasContent = !!collapsedSummary
    const [isRowExpanded, setIsRowExpanded] = useState(() => {
        // Snapshots will display all editor filter groups by default
        if (inStorybook() || inStorybookTestRunner()) {
            return true
        }

        // Auto-expand when there's configured content, even if defaultExpanded is false
        if (defaultExpanded === false && hasContent) {
            return true
        }

        // If not specified, the group is expanded
        return defaultExpanded ?? true
    })

    // If defaultExpanded is not set, the group is not expandable
    const isExpandable = defaultExpanded != undefined

    if (asTile) {
        return (
            <div className="border rounded bg-surface-primary min-w-0">
                {isExpandable ? (
                    <LemonButton
                        fullWidth
                        onClick={() => {
                            const newState = !isRowExpanded
                            setIsRowExpanded(newState)
                            posthog.capture('editor panel section toggled', {
                                section: title,
                                action: newState ? 'opened' : 'closed',
                            })
                        }}
                        sideIcon={isRowExpanded ? <IconCollapse /> : <IconExpand />}
                        title={isRowExpanded ? 'Show less' : 'Show more'}
                        data-attr={'editor-filter-group-collapse-' + slugify(title)}
                        className={clsx('rounded-b-none', isRowExpanded && 'mb-1')}
                    >
                        <div className="flex items-center gap-2 font-semibold text-[13px]">
                            <span>{title}</span>
                            {!isRowExpanded && collapsedSummary && (
                                <span className="text-xs font-normal text-secondary">{collapsedSummary}</span>
                            )}
                        </div>
                    </LemonButton>
                ) : (
                    <div className="px-3 py-2">
                        <span className="text-[13px] font-semibold text-secondary">{title}</span>
                    </div>
                )}
                <div
                    className="grid transition-all duration-200 ease-in-out"
                    style={{ gridTemplateRows: isRowExpanded ? '1fr' : '0fr' }}
                >
                    <div className="overflow-hidden">
                        <div className="px-3 pb-3 pt-2 flex flex-col gap-2 min-w-0">
                            {editorFilters.map(({ label: Label, tooltip, showOptional, key, component: Component }) => {
                                if (Component && Component.name === 'component') {
                                    throw new Error(
                                        `Component for filter ${key} is an anonymous function, which is not a valid React component! Use a named function instead.`
                                    )
                                }
                                return (
                                    <Fragment key={key}>
                                        <LemonField.Pure
                                            label={
                                                typeof Label === 'function' ? (
                                                    <Label insightProps={insightProps} />
                                                ) : (
                                                    Label
                                                )
                                            }
                                            info={tooltip}
                                            showOptional={showOptional}
                                        >
                                            {Component ? <Component insightProps={insightProps} /> : null}
                                        </LemonField.Pure>
                                    </Fragment>
                                )
                            })}
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div>
            {isExpandable && (
                <LemonButton
                    fullWidth
                    onClick={() => setIsRowExpanded(!isRowExpanded)}
                    sideIcon={isRowExpanded ? <IconCollapse /> : <IconExpand />}
                    title={isRowExpanded ? 'Show less' : 'Show more'}
                    data-attr={'editor-filter-group-collapse-' + slugify(title)}
                >
                    <div className="flex items-center gap-2 font-semibold">
                        <span>{title}</span>
                        {!isRowExpanded && collapsedSummary && (
                            <span className="text-xs font-normal text-secondary">{collapsedSummary}</span>
                        )}
                    </div>
                </LemonButton>
            )}

            {isRowExpanded && (
                <div
                    className={clsx('flex flex-col gap-2', {
                        'border rounded p-2 mt-1': isExpandable && isRowExpanded,
                    })}
                >
                    {editorFilters.map(({ label: Label, tooltip, showOptional, key, component: Component }) => {
                        if (Component && Component.name === 'component') {
                            throw new Error(
                                `Component for filter ${key} is an anonymous function, which is not a valid React component! Use a named function instead.`
                            )
                        }
                        return (
                            <Fragment key={key}>
                                <LemonField.Pure
                                    label={typeof Label === 'function' ? <Label insightProps={insightProps} /> : Label}
                                    info={tooltip}
                                    showOptional={showOptional}
                                >
                                    {Component ? <Component insightProps={insightProps} /> : null}
                                </LemonField.Pure>
                            </Fragment>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
