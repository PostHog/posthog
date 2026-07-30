import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { notebookTemplatesLogic } from './notebookTemplatesLogic'

export function NotebookTemplateCards(): JSX.Element {
    const { templates, creatingTemplate } = useValues(notebookTemplatesLogic)
    const { createNotebookFromTemplate } = useActions(notebookTemplatesLogic)

    return (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
            {templates.map((template) => (
                <LemonCard key={template.short_id} className="flex flex-col gap-2" hoverEffect={false}>
                    <h3 className="mb-0">{template.title}</h3>
                    <p className="grow text-secondary mb-0">{template.description}</p>
                    <div className="flex items-center gap-2">
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Notebook}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                size="small"
                                data-attr="use-notebook-template"
                                onClick={() => createNotebookFromTemplate(template.short_id)}
                                loading={creatingTemplate === template.short_id}
                                // `undefined` rather than `false` so AccessControlAction can still
                                // supply its own disabled state when no create is in flight
                                disabled={creatingTemplate !== null || undefined}
                            >
                                Use template
                            </LemonButton>
                        </AccessControlAction>
                        <LemonButton type="secondary" size="small" to={urls.notebook(template.short_id)}>
                            Preview
                        </LemonButton>
                    </div>
                </LemonCard>
            ))}
        </div>
    )
}
