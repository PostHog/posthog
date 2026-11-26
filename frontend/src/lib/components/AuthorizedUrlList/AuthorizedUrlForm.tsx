import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { ExperimentIdType } from '~/types'

import { AuthorizedUrlListType, authorizedUrlListLogic } from './authorizedUrlListLogic'
import { QuillAuthorizedUrlForm } from './QuillAuthorizedUrlForm'

export interface AuthorizedUrlFormProps {
    type: AuthorizedUrlListType
    actionId?: number
    experimentId?: ExperimentIdType
    productTourId?: string | null
    allowWildCards?: boolean
}

export function AuthorizedUrlForm({
    actionId,
    experimentId,
    productTourId,
    type,
    allowWildCards,
}: AuthorizedUrlFormProps): JSX.Element {
    const logicProps = {
        actionId: actionId ?? null,
        experimentId: experimentId ?? null,
        productTourId: productTourId ?? null,
        type,
        allowWildCards,
    }
    const logic = authorizedUrlListLogic(logicProps)
    const { isProposedUrlSubmitting } = useValues(logic)
    const { cancelProposingUrl } = useActions(logic)
    const quillSurface = useQuillSurface()

    const placeholder = allowWildCards
        ? 'Enter a URL or wildcard subdomain (e.g. https://*.posthog.com)'
        : 'Enter a URL (e.g. https://posthog.com)'

    if (quillSurface) {
        return (
            <QuillAuthorizedUrlForm
                logicProps={logicProps}
                placeholder={placeholder}
                submitting={isProposedUrlSubmitting}
                onCancel={cancelProposingUrl}
            />
        )
    }

    return (
        <Form
            logic={authorizedUrlListLogic}
            props={logicProps}
            formKey="proposedUrl"
            enableFormOnSubmit
            className="w-full deprecated-space-y-2"
        >
            <LemonField name="url">
                <LemonInput autoFocus placeholder={placeholder} data-attr="url-input" />
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
