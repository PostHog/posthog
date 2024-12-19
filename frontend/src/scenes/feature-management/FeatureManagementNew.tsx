import { LemonButton, LemonDivider, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { featureManagementNewLogic } from './featureManagementNewLogic'

export const scene: SceneExport = {
    component: FeatureManagementNew,
    logic: featureManagementNewLogic,
}

function FeatureManagementNew(): JSX.Element {
    const { props } = useValues(featureManagementNewLogic)

    return (
        <Form
            id="feature-creation"
            logic={featureManagementNewLogic}
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
                        <LemonButton type="primary" data-attr="save-feature-flag" htmlType="submit" form="feature-flag">
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
                <LemonButton type="primary" data-attr="save-feature-flag" htmlType="submit" form="feature-flag">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
