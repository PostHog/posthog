import { LemonBanner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { actionsModel } from '~/models/actionsModel'

import { LocalFilter } from '../entityFilterLogic'
import { filterToActionStep, generateActionNameFromFilter, isAutocaptureFilterWithElements } from './saveAsActionUtils'

function handleSaveAsAction(filter: LocalFilter): void {
    const suggestedName = generateActionNameFromFilter(filter)

    LemonDialog.openForm({
        title: 'Save as action',
        initialValues: { actionName: suggestedName },
        shouldAwaitSubmit: true,
        content: (
            <LemonField name="actionName" label="Action name">
                <LemonInput data-attr="save-as-action-name" placeholder="Action name" autoFocus />
            </LemonField>
        ),
        onSubmit: async ({ actionName }) => {
            const step = filterToActionStep(filter)
            try {
                const action = await api.actions.create({ name: actionName, steps: [step] })
                actionsModel.findMounted()?.actions.loadActions()
                lemonToast.success(
                    <>
                        Action created. <Link to={urls.action(action.id)}>View action</Link>
                    </>
                )
            } catch {
                lemonToast.error('Failed to create action. Please try again.')
            }
        },
    })
}

interface SaveAsActionBannerProps {
    filter: LocalFilter
}

export function SaveAsActionBanner({ filter }: SaveAsActionBannerProps): JSX.Element | null {
    if (!isAutocaptureFilterWithElements(filter)) {
        return null
    }

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.AUTOCAPTURE_SAVE_AS_ACTION}>
            <LemonBanner
                type="info"
                className="mt-2"
                dismissKey="autocapture-save-as-action-nudge"
                action={{
                    children: 'Save as action',
                    onClick: () => handleSaveAsAction(filter),
                    'data-attr': 'autocapture-save-as-action',
                }}
            >
                Save these filters as a reusable action.
            </LemonBanner>
        </FlaggedFeature>
    )
}
