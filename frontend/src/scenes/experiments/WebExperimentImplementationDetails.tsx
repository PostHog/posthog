import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { Experiment } from '~/types'

export const WEB_IMPLEMENTATION_HELP =
    'Define variant changes directly on your website. Use our toolbar to select elements and apply transformations for each variant.'

export function toolbarDomainDescription(hasExperimentId: boolean): string {
    return hasExperimentId
        ? 'Choose the domain on which to edit this experiment'
        : 'Choose the domain on which to create this experiment'
}

interface WebExperimentImplementationDetails {
    experiment: Partial<Experiment> | null
}
export function WebExperimentImplementationDetails({ experiment }: WebExperimentImplementationDetails): JSX.Element {
    const onSelectElement = (): void => {
        LemonDialog.open({
            title: 'Select a domain',
            description: toolbarDomainDescription(!!experiment?.id),
            content: (
                <>
                    <AuthorizedUrlList experimentId={experiment?.id} type={AuthorizedUrlListType.TOOLBAR_URLS} />
                </>
            ),
            primaryButton: {
                children: 'Close',
                type: 'secondary',
            },
        })
    }

    return (
        <div className="space-y-2">
            <h2 className="font-semibold text-lg mb-0">Implementation</h2>
            <div className="text-sm text-secondary">{WEB_IMPLEMENTATION_HELP}</div>
            <div>
                <LemonButton size="small" type="secondary" onClick={onSelectElement} sideIcon={<IconOpenInApp />}>
                    Launch toolbar on your website
                </LemonButton>
            </div>
        </div>
    )
}
