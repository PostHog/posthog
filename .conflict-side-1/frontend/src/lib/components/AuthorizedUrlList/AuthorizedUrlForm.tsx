import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { ExperimentIdType } from '~/types'

import { AuthorizedUrlListType, authorizedUrlListLogic } from './authorizedUrlListLogic'

export interface AuthorizedUrlFormProps {
    type: AuthorizedUrlListType
    actionId?: number
    experimentId?: ExperimentIdType
    allowWildCards?: boolean
}

export function AuthorizedUrlForm({
    actionId,
    experimentId,
    type,
    allowWildCards,
}: AuthorizedUrlFormProps): JSX.Element {
    const logic = authorizedUrlListLogic({
        actionId: actionId ?? null,
        experimentId: experimentId ?? null,
        type,
        allowWildCards,
    })
    const { isProposedUrlSubmitting } = useValues(logic)
    const { cancelProposingUrl } = useActions(logic)

    return (
        <Form
            logic={authorizedUrlListLogic}
            props={{ actionId: actionId ?? null, experimentId: experimentId ?? null, type, allowWildCards }}
            formKey="proposedUrl"
            enableFormOnSubmit
            className="w-full deprecated-space-y-2"
        >
            <LemonField name="url">
                <LemonInput
                    autoFocus
                    placeholder={
                        allowWildCards
                            ? 'Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)'
                            : 'Enter a URL (e.g. https://posthog.com)'
                    }
                    data-attr="url-input"
                />
            </LemonField>
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={cancelProposingUrl}>
                    Cancel
                </LemonButton>
                <LemonButton htmlType="submit" type="primary" loading={isProposedUrlSubmitting} data-attr="url-save">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
