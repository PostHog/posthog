import clsx from 'clsx'
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
}

export function EditorFilterGroup({ insightProps, editorFilterGroup }: EditorFilterGroupProps): JSX.Element {
    const { title, defaultExpanded, editorFilters } = editorFilterGroup
    const [isRowExpanded, setIsRowExpanded] = useState(() => {
        // Snapshots will display all editor filter groups by default
        if (inStorybook() || inStorybookTestRunner()) {
            return true
        }

        // If not specified, the group is expanded
        return defaultExpanded ?? true
    })

    // If defaultExpanded is not set, the group is not expandable
    const isExpandable = defaultExpanded != undefined

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
                    <div className="flex items-center deprecated-space-x-2 font-semibold">
                        <span>{title}</span>
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
