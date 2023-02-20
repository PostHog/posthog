import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { newDashboardTemplateLogic } from './NewDashboardTemplateLogic'

export function NewDashboardTemplate(): JSX.Element {
    const monaco = useMonaco()

    const { dashboardTemplateJSON } = useValues(newDashboardTemplateLogic)
    const { setDashboardTemplateJSON } = useActions(newDashboardTemplateLogic)

    const { setOpenNewDashboardTemplateModal } = useActions(newDashboardTemplateLogic)
    const { isOpenNewDashboardTemplateModal } = useValues(newDashboardTemplateLogic)

    const { createDashboardTemplate, updateDashboardTemplate } = useActions(newDashboardTemplateLogic)

    const { id } = useValues(newDashboardTemplateLogic)

    // const [queryInput, setQueryInput] = useState('hello')

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: [
                {
                    uri: 'http://internal/node-schema.json',
                    fileMatch: ['*'], // associate with our model
                },
            ],
        })
    }, [monaco])

    return (
        <LemonModal
            title="New Dashboard Template"
            isOpen={isOpenNewDashboardTemplateModal}
            width={800}
            onClose={() => {
                setOpenNewDashboardTemplateModal(false)
            }}
        >
            <MonacoEditor
                theme="vs-light"
                className="border"
                language="json"
                value={dashboardTemplateJSON}
                onChange={(v) => setDashboardTemplateJSON(v ?? '')}
                height={500}
            />
            <div className="flex justify-end">
                {id ? (
                    <LemonButton
                        onClick={() => {
                            updateDashboardTemplate(id)
                        }}
                    >
                        Update template
                    </LemonButton>
                ) : (
                    <LemonButton
                        onClick={() => {
                            createDashboardTemplate(dashboardTemplateJSON)
                            setOpenNewDashboardTemplateModal(false)
                        }}
                    >
                        Create new template
                    </LemonButton>
                )}
            </div>
        </LemonModal>
    )
}
