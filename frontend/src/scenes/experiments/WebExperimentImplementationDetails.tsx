import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { IconOpenInApp } from 'lib/lemon-ui/icons'

import { Experiment } from '~/types'

interface WebExperimentImplementationDetails {
    experiment: Partial<Experiment> | null
}
export function WebExperimentImplementationDetails({ experiment }: WebExperimentImplementationDetails): JSX.Element {
    const onSelectElement = (): void => {
        LemonDialog.open({
            title: 'Select a domain',
            description: experiment?.id
                ? 'Choose the domain on which to edit this experiment'
                : 'Choose the domain on which to create this experiment',
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
        <>
            <div>
                <div className="border p-6 rounded bg-surface-primary deprecated-space-y-2">
                    <div className="font-semibold leading-tight text-base text-current">
                        Define variant changes directly on your website
                    </div>
                    <div className="text-sm text-secondary">
                        Use our toolbar to select elements and apply transformations for each variant.
                    </div>
                    <div>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={onSelectElement}
                            sideIcon={<IconOpenInApp />}
                        >
                            Launch toolbar on your website
                        </LemonButton>
                    </div>
                </div>
            </div>
        </>
    )
}
