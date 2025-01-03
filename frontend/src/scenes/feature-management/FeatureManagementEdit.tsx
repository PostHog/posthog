import { LemonButton, LemonDivider, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { featureManagementEditLogic } from './featureManagementEditLogic'

export const scene: SceneExport = {
    component: FeatureManagementEdit,
    logic: featureManagementEditLogic,
    paramsToProps: ({ params: { id } }): (typeof featureManagementEditLogic)['props'] => ({
        id: id && id !== 'new' ? id : 'new',
    }),
}

function FeatureManagementEdit(): JSX.Element {
    const { props } = useValues(featureManagementEditLogic)

    return (
        <Form
            id="feature-creation"
            logic={featureManagementEditLogic}
            props={props}
            formKey="feature"
            enableFormOnSubmit
            className="space-y-4"
        >
            <PageHeader
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-feature-flag"
                            type="secondary"
                            onClick={() => router.actions.push(urls.featureManagement())}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-feature-flag"
                            htmlType="submit"
                            form="feature-creation"
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            />
            <div className="my-4">
                <div className="max-w-1/2 space-y-4">
                    <LemonField name="name" label="Name">
                        <LemonInput
                            data-attr="feature-name"
                            className="ph-ignore-input"
                            autoFocus
                            placeholder="examples: Login v2, New registration flow, Mobile web"
                            autoComplete="off"
                            autoCapitalize="off"
                            autoCorrect="off"
                            spellCheck={false}
                        />
                    </LemonField>

                    <LemonField name="key" label="Key">
                        <LemonInput
                            data-attr="feature-key"
                            className="ph-ignore-input"
                            autoComplete="off"
                            autoCapitalize="off"
                            autoCorrect="off"
                            spellCheck={false}
                            disabled
                        />
                    </LemonField>
                    <span className="text-muted text-sm">
                        This will be used to monitor feature usage. Feature keys must be unique to other features and
                        feature flags.
                    </span>

                    <LemonField name="description" label="Description">
                        <LemonTextArea className="ph-ignore-input" data-attr="feature-description" />
                    </LemonField>
                </div>
            </div>
            <LemonDivider />

            <div className="flex items-center gap-2 justify-end">
                <LemonButton
                    data-attr="cancel-feature-flag"
                    type="secondary"
                    onClick={() => router.actions.push(urls.featureManagement())}
                >
                    Cancel
                </LemonButton>
                <LemonButton type="primary" data-attr="save-feature-flag" htmlType="submit" form="feature-creation">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
