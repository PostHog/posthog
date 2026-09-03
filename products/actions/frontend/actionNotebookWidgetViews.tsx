import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { actionLogic } from './logics/actionLogic'
import { ActionEdit } from './pages/ActionEdit'
import { ActionStepConditions } from './utils/actionStepDescription'

export type ActionNotebookWidgetAttributes = {
    id: number
    view?: string
}

function ActionMetadata({ attributes }: NotebookNodeProps<ActionNotebookWidgetAttributes>): null {
    const { action } = useValues(actionLogic({ id: attributes.id }))
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(action?.name || 'Action')
    }, [action?.name, setTitlePlaceholder])

    return null
}

function ActionLoading(): JSX.Element {
    return (
        <div className="p-3">
            <LemonSkeleton className="h-6 w-full" />
        </div>
    )
}

function ActionSummary({ attributes }: NotebookNodeProps<ActionNotebookWidgetAttributes>): JSX.Element {
    const { action, actionLoading } = useValues(actionLogic({ id: attributes.id }))

    if (!action && actionLoading) {
        return <ActionLoading />
    }
    if (!action) {
        return <NotFound object="action" />
    }

    const stepCount = action.steps?.length || 0

    return (
        <>
            <ActionMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="flex flex-wrap items-center gap-2 p-3">
                <span className="min-w-48 flex-1 truncate">{action.description || 'No description'}</span>
                <LemonTag type="muted">
                    {stepCount} {stepCount === 1 ? 'step' : 'steps'}
                </LemonTag>
            </div>
        </>
    )
}

export function ActionDetail({ attributes }: NotebookNodeProps<ActionNotebookWidgetAttributes>): JSX.Element {
    const { action, actionLoading } = useValues(actionLogic({ id: attributes.id }))

    if (!action && actionLoading) {
        return <ActionLoading />
    }
    if (!action) {
        return <NotFound object="action" />
    }

    return (
        <BindLogic logic={actionLogic} props={{ id: attributes.id }}>
            <ActionMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="flex flex-col gap-3 p-3">
                {action.description ? <p className="text-secondary">{action.description}</p> : null}
                {action.steps?.length ? (
                    action.steps.map((step, index) => (
                        <div className="rounded border p-3" key={index}>
                            <ActionStepConditions step={step} />
                        </div>
                    ))
                ) : (
                    <span className="text-secondary">This action has no matching steps.</span>
                )}
            </div>
        </BindLogic>
    )
}

function ActionEditor({ attributes }: NotebookNodeProps<ActionNotebookWidgetAttributes>): JSX.Element {
    const logic = actionLogic({ id: attributes.id })
    const { action, actionLoading } = useValues(logic)

    return (
        <BindLogic logic={actionLogic} props={{ id: attributes.id }}>
            <ActionMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="max-h-[48rem] overflow-auto p-3">
                <ActionEdit id={attributes.id} action={action} actionLoading={actionLoading} attachTo={logic} />
            </div>
        </BindLogic>
    )
}

export const ACTION_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<ActionNotebookWidgetAttributes, 'Action'>(
    'Action',
    {
        summary: ActionSummary,
        editor: ActionEditor,
    }
)
