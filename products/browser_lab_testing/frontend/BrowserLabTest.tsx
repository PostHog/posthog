import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BrowserLabTestLogicProps, browserLabTestLogic } from './browserLabTestLogic'

export const scene: SceneExport<BrowserLabTestLogicProps> = {
    component: BrowserLabTestScene,
    logic: browserLabTestLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id && id !== 'new' ? id : 'new' }),
}

function SecretsEditor(): JSX.Element {
    const { browserLabTest } = useValues(browserLabTestLogic)
    const { setBrowserLabTestValue } = useActions(browserLabTestLogic)

    const secrets = browserLabTest?.secrets || {}
    const secretEntries = Object.entries(secrets)

    const addSecret = (): void => {
        const key = `SECRET_${secretEntries.length + 1}`
        setBrowserLabTestValue('secrets', { ...secrets, [key]: '' })
    }

    const removeSecret = (key: string): void => {
        const updated = { ...secrets }
        delete updated[key]
        setBrowserLabTestValue('secrets', updated)
    }

    const updateSecretKey = (oldKey: string, newKey: string): void => {
        if (oldKey === newKey) {
            return
        }
        const entries = Object.entries(secrets) as [string, string | { secret: true }][]
        const updated: Record<string, string | { secret: true }> = {}
        for (const [k, v] of entries) {
            updated[k === oldKey ? newKey : k] = v
        }
        setBrowserLabTestValue('secrets', updated)
    }

    const updateSecretValue = (key: string, value: string): void => {
        setBrowserLabTestValue('secrets', { ...secrets, [key]: value })
    }

    return (
        <div className="space-y-2">
            {secretEntries.map(([key, value]) => {
                const isExisting =
                    typeof value === 'object' && value !== null && (value as { secret: boolean }).secret === true
                return (
                    <div key={key} className="flex items-center gap-2">
                        <LemonInput
                            value={key}
                            onChange={(newKey) => updateSecretKey(key, newKey)}
                            placeholder="KEY_NAME"
                            className="flex-1"
                        />
                        <LemonInput
                            type="password"
                            value={isExisting ? '' : (value as string)}
                            onChange={(val) => updateSecretValue(key, val)}
                            placeholder={isExisting ? 'Leave unchanged' : 'Secret value'}
                            className="flex-1"
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            size="small"
                            status="danger"
                            onClick={() => removeSecret(key)}
                        />
                    </div>
                )
            })}
            <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={addSecret}>
                Add secret
            </LemonButton>
        </div>
    )
}

export function BrowserLabTestScene({ id }: BrowserLabTestLogicProps): JSX.Element {
    const { browserLabTest, browserLabTestLoading, isBrowserLabTestSubmitting, browserLabTestMissing } =
        useValues(browserLabTestLogic)
    const { submitBrowserLabTest } = useActions(browserLabTestLogic)

    if (browserLabTestMissing) {
        return <NotFound object="browser lab test" />
    }

    const isNew = id === 'new'

    return (
        <SceneContent>
            <SceneTitleSection
                name={isNew ? 'New browser lab test' : browserLabTest?.name || 'Loading...'}
                resourceType={{ type: 'default' }}
            />
            <Form logic={browserLabTestLogic} formKey="browserLabTest" enableFormOnSubmit className="space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="My test" />
                </LemonField>

                <LemonField name="url" label="URL">
                    <LemonInput placeholder="https://example.com" />
                </LemonField>

                <LemonField name="steps" label="Steps (JSON)">
                    {({ value, onChange }) => (
                        <LemonTextArea
                            value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
                            onChange={(val) => {
                                try {
                                    onChange(JSON.parse(val))
                                } catch {
                                    onChange(val)
                                }
                            }}
                            minRows={4}
                            placeholder='[{"action": "click", "selector": "#button"}]'
                        />
                    )}
                </LemonField>

                <div>
                    <label className="font-semibold text-sm">
                        Secrets
                        <p className="font-normal text-muted mt-1 mb-2">
                            Store credentials encrypted at rest. Reference them in steps with{' '}
                            <code className="text-xs">{'{{secrets.KEY_NAME}}'}</code>.
                        </p>
                    </label>
                    <SecretsEditor />
                </div>

                <div className="flex gap-2">
                    <LemonButton
                        type="primary"
                        onClick={submitBrowserLabTest}
                        loading={isBrowserLabTestSubmitting}
                        disabled={browserLabTestLoading}
                    >
                        {isNew ? 'Create' : 'Save'}
                    </LemonButton>
                    <LemonButton type="secondary" onClick={() => router.actions.push(urls.browserLabTests())}>
                        Cancel
                    </LemonButton>
                </div>
            </Form>
        </SceneContent>
    )
}

export default BrowserLabTestScene
