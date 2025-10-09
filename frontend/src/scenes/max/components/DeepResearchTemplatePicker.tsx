import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import api from 'lib/api'
import { NotebookTarget } from 'scenes/notebooks/types'
import { projectLogic } from 'scenes/projectLogic'

import { notebooksModel } from '~/models/notebooksModel'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

export function DeepResearchTemplatePicker(): JSX.Element | null {
    const { deepResearchMode, threadRaw, deepResearchTemplate } = useValues(maxThreadLogic)
    const { setDeepResearchTemplate } = useActions(maxThreadLogic)
    const { setQuestion } = useActions(maxLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { createNotebook } = useActions(notebooksModel)

    // Don't show the template picker if conversation has already started (has human messages)
    const hasHumanMessages = threadRaw?.some((msg) => msg.type === AssistantMessageType.Human) || false
    if (!deepResearchMode || hasHumanMessages) {
        return null
    }

    const handleCreateCustomTemplate = (): void => {
        // Backend will automatically populate with DEFAULT_CUSTOM_DEEP_RESEARCH_NOTEBOOK when tags include template_deep_research
        createNotebook(NotebookTarget.Scene, undefined, undefined, undefined, ['template_deep_research'])
    }

    return (
        <LemonDropdown
            overlay={
                <div className="flex flex-col p-1 min-w-60">
                    <div className="px-1 pb-1 text-muted text-xs">Curated templates</div>
                    <RemoteNotebookTemplates
                        currentProjectId={currentProjectId}
                        setDeepResearchTemplate={setDeepResearchTemplate}
                    />
                    <div className="border-t border-border mt-1 pt-1">
                        <LemonButton onClick={handleCreateCustomTemplate} fullWidth size="small" type="secondary">
                            Create custom template
                        </LemonButton>
                    </div>
                    {deepResearchTemplate && (
                        <LemonButton
                            className="mt-1"
                            onClick={() => {
                                setDeepResearchTemplate(null)
                                setQuestion('')
                            }}
                            fullWidth
                            size="small"
                            type="secondary"
                        >
                            Clear template
                        </LemonButton>
                    )}
                </div>
            }
        >
            <LemonButton size="small" type={deepResearchTemplate ? 'primary' : 'secondary'}>
                {deepResearchTemplate ? 'Template selected' : 'Select template'}
            </LemonButton>
        </LemonDropdown>
    )
}

function RemoteNotebookTemplates({
    currentProjectId,
    setDeepResearchTemplate,
}: {
    currentProjectId: number | null
    setDeepResearchTemplate: (ref: any) => void
}): JSX.Element {
    const [items, setItems] = useState<Array<{ short_id: string; title: string }>>([])
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        let mounted = true
        if (!currentProjectId) {
            setItems([])
            return
        }
        setLoading(true)
        const url = `api/projects/${currentProjectId}/notebooks?tags=template_deep_research`
        api.get(url)
            .then((res) => {
                const results = (res?.results || res || []) as Array<{ short_id: string; title: string }>
                if (mounted) {
                    setItems(results)
                }
            })
            .finally(() => {
                if (mounted) {
                    setLoading(false)
                }
            })
        return () => {
            mounted = false
        }
    }, [currentProjectId])

    if (loading) {
        return <div className="px-1 py-0.5 text-xs text-muted">Loading…</div>
    }

    if (!items.length) {
        return <div className="px-1 py-0.5 text-xs text-muted">No curated templates found</div>
    }

    return (
        <>
            {items.map((n) => (
                <LemonButton
                    key={n.short_id}
                    onClick={() => {
                        setDeepResearchTemplate({ notebook_short_id: n.short_id, notebook_title: n.title })
                    }}
                    fullWidth
                    size="small"
                    type="tertiary"
                >
                    {n.title}
                </LemonButton>
            ))}
        </>
    )
}
